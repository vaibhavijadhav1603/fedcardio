"""Federated training orchestration. Jobs run the fl_engine simulator over the 4 UCI hospital
partitions in a background worker; progress is streamed into the database round by round.
(In the docker-compose deployment the same strategies also run over real network nodes with
Flower; see fl_engine/flower_app.)"""
from __future__ import annotations

import math
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import SessionLocal, get_db
from ..models import FLNode, TrainingJob, User
from ..security import Perm, require

router = APIRouter(prefix="/fl", tags=["federated"])
_pool = ThreadPoolExecutor(max_workers=1)
_cancel: dict[int, threading.Event] = {}


class JobIn(BaseModel):
    name: str = Field(default="", max_length=120)
    model: str = Field(default="paper_nn", pattern="^(paper_nn|lr|mlp)$")
    algorithm: str = Field(default="fedavg", pattern="^(fedavg|fedprox|scaffold|fedadam|fedbn)$")
    privacy: str = Field(default="none", pattern="^(none|svt|dpsgd|he|secagg|dpsgd\\+he|dpsgd\\+secagg)$")
    rounds: int = Field(default=30, ge=1, le=300)
    local_epochs: int = Field(default=5, ge=1, le=50)
    lr: float = Field(default=0.01, gt=0, le=1)
    prox_mu: float = Field(default=0.0, ge=0, le=10)
    dp_epsilon: float = Field(default=3.0, gt=0, le=100)
    class_weight: bool = False
    dropout_prob: float = Field(default=0.0, ge=0, lt=1)

    @model_validator(mode="after")
    def valid_combo(self):
        if self.algorithm == "scaffold" and "dpsgd" in self.privacy:
            raise ValueError("SCAFFOLD cannot be combined with DP-SGD (control variates are not privatised)")
        if self.algorithm == "fedprox" and self.prox_mu == 0:
            self.prox_mu = 0.01
        return self


def job_out(j: TrainingJob) -> dict:
    def clean(v):
        return None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v
    return {"id": j.id, "name": j.name, "config": j.config, "status": j.status, "progress": j.progress,
            "history": [{k: clean(v) for k, v in h.items()} for h in (j.history or [])],
            "metrics": {k: clean(v) for k, v in (j.metrics or {}).items()},
            "epsilon": clean(j.epsilon), "bytes_up": j.bytes_up, "error": j.error,
            "created_at": j.created_at.isoformat(), "finished_at": j.finished_at and j.finished_at.isoformat()}


def _run(job_id: int):
    import numpy as np
    from sklearn.model_selection import train_test_split

    from fl_engine.data.federated import fit_federated
    from fl_engine.data.loaders import load_uci_heart
    from fl_engine.data.preprocess import SPECS
    from fl_engine.eval.metrics import THRESHOLD_RULES, operating_point, threshold_free
    from fl_engine.sim import Client, FLConfig, run_federated

    db = SessionLocal()
    job = db.get(TrainingJob, job_id)
    try:
        job.status = "running"
        db.commit()
        cfg_d = dict(job.config)
        df = load_uci_heart()
        splits = {}
        for s, g in df.groupby("site"):
            tr, te = train_test_split(g, test_size=0.2, stratify=g.y, random_state=0)
            itr, va = train_test_split(tr, test_size=0.2, stratify=tr.y, random_state=0)
            splits[s] = (itr, va, te)
        scaler = "minmax" if cfg_d["model"] == "lr" else "standard"
        pp = fit_federated([v[0] for v in splits.values()], SPECS["uci_main"], scaler=scaler)
        clients = [Client(s, pp.transform(a), a.y.to_numpy().astype(np.float32), pp.transform(b),
                          b.y.to_numpy().astype(np.float32)) for s, (a, b, _) in splits.items()]
        extra = {}
        if "dpsgd" in cfg_d["privacy"]:
            extra = {"dp_sample_rate": 0.2, "dp_lr": 0.5, "local_epochs": 1}
        cfg = FLConfig(model=cfg_d["model"], algorithm=cfg_d["algorithm"], privacy=cfg_d["privacy"],
                       rounds=cfg_d["rounds"], local_epochs=cfg_d["local_epochs"], lr=cfg_d["lr"],
                       batch_size=20000, prox_mu=cfg_d["prox_mu"], dp_epsilon=cfg_d["dp_epsilon"],
                       class_weight=cfg_d["class_weight"], dropout_prob=cfg_d["dropout_prob"], eval_every=1,
                       **extra)
        Xv = np.vstack([c.X_val for c in clients])
        yv = np.concatenate([c.y_val for c in clients])
        stop = _cancel.setdefault(job_id, threading.Event())

        def on_round(entry):
            j = db.get(TrainingJob, job_id)
            j.history = [*(j.history or []), entry]
            j.progress = entry["round"] / cfg.rounds
            j.bytes_up = int(entry.get("bytes_up", 0))
            db.commit()

        res = run_federated(clients, cfg, Xv, yv, on_round=on_round, should_stop=stop.is_set)
        pv = np.concatenate([res.predict(c.name, c.X_val) for c in clients])
        thr = THRESHOLD_RULES["youden"](yv, pv)
        Xt = np.vstack([pp.transform(splits[s][2]) for s in splits])
        yt = np.concatenate([splits[s][2].y.to_numpy() for s in splits])
        pt = np.concatenate([res.predict(s, pp.transform(splits[s][2])) for s in splits])
        per_site = {s: threshold_free(splits[s][2].y.to_numpy(), res.predict(s, pp.transform(splits[s][2])))["auroc"]
                    for s in splits}
        job = db.get(TrainingJob, job_id)
        job.metrics = {**threshold_free(yt, pt), **operating_point(yt, pt, thr), "n_test": int(len(Xt)),
                       **{f"auroc_{k}": v for k, v in per_site.items()}, "wall_seconds": res.wall_seconds,
                       "bytes_down": res.bytes_down, **({"he_" + k: v for k, v in res.he.items()} if res.he else {})}
        job.epsilon = res.epsilon
        job.bytes_up = int(res.bytes_up)
        job.status = "cancelled" if stop.is_set() else "completed"
        job.progress = 1.0 if job.status == "completed" else job.progress
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        audit.log(db, "fl.job_finished", resource=f"job:{job_id}", detail={"status": job.status, "auroc": job.metrics.get("auroc")})
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        db.rollback()
        job = db.get(TrainingJob, job_id)
        job.status, job.error = "failed", f"{e}\n{traceback.format_exc()[-1500:]}"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


@router.get("/nodes")
def nodes(_: User = Depends(require(Perm.fl_view)), db: Session = Depends(get_db)):
    return [{"id": n.id, "name": n.name, "hospital": n.hospital.name, "hospital_id": n.hospital_id, "status": n.status,
             "n_records": n.n_records, "cert_fingerprint": n.cert_fingerprint, "last_seen": n.last_seen.isoformat()}
            for n in db.query(FLNode).order_by(FLNode.id)]


@router.get("/jobs")
def jobs(_: User = Depends(require(Perm.fl_view)), db: Session = Depends(get_db)):
    return [job_out(j) for j in db.query(TrainingJob).order_by(TrainingJob.id.desc()).limit(50)]


@router.get("/jobs/{jid}")
def job(jid: int, _: User = Depends(require(Perm.fl_view)), db: Session = Depends(get_db)):
    j = db.get(TrainingJob, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    return job_out(j)


@router.post("/jobs", status_code=201)
def launch(body: JobIn, user: User = Depends(require(Perm.fl_run)), db: Session = Depends(get_db)):
    active = db.query(TrainingJob).filter(TrainingJob.status.in_(["queued", "running"])).count()
    if active >= 3:
        raise HTTPException(429, "too many active jobs; wait for one to finish")
    name = body.name or f"{body.algorithm.upper()} · {body.model} · {body.privacy}"
    j = TrainingJob(name=name, config=body.model_dump(), created_by=user.id)
    db.add(j)
    db.commit()
    audit.log(db, "fl.job_launch", user=user, resource=f"job:{j.id}", detail=body.model_dump())
    _pool.submit(_run, j.id)
    return job_out(j)


@router.post("/jobs/{jid}/cancel")
def cancel(jid: int, user: User = Depends(require(Perm.fl_run)), db: Session = Depends(get_db)):
    j = db.get(TrainingJob, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    if j.status in ("queued", "running"):
        _cancel.setdefault(jid, threading.Event()).set()
        if j.status == "queued":
            j.status = "cancelled"
            db.commit()
        audit.log(db, "fl.job_cancel", user=user, resource=f"job:{jid}")
    return job_out(j)
