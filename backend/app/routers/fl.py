"""Federated training orchestration. Jobs run the fl_engine simulator over the datasets of every
active hospital (each one is a client, decrypted only inside its own partition) in a background
worker; progress is streamed into the database round by round.
(In the docker-compose deployment the same strategies also run over real network nodes with
Flower; see fl_engine/flower_app.)"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from .. import audit, datasets
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import FLNode, Hospital, ModelVersion, TrainingJob, User
from ..security import Perm, require

router = APIRouter(prefix="/fl", tags=["federated"])
_pool = ThreadPoolExecutor(max_workers=1)
_cancel: dict[int, threading.Event] = {}
MIN_SITES = 2


class JobIn(BaseModel):
    name: str = Field(default="", max_length=120)
    model: str = Field(default="paper_nn", pattern="^(paper_nn|lr|mlp)$")
    algorithm: str = Field(default="fedavg", pattern="^(fedavg|fedprox|scaffold)$")
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


def job_out(j: TrainingJob, db: Session | None = None) -> dict:
    def clean(v):
        return None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v
    return {"id": j.id, "name": j.name, "config": j.config, "status": j.status, "progress": j.progress,
            "history": [{k: clean(v) for k, v in h.items()} for h in (j.history or [])],
            "metrics": {k: clean(v) for k, v in (j.metrics or {}).items()},
            "epsilon": clean(j.epsilon), "bytes_up": j.bytes_up, "error": j.error,
            "created_at": j.created_at.isoformat(), "finished_at": j.finished_at and j.finished_at.isoformat(),
            "registrable": j.status == "completed" and _card_path(j.id).exists(),
            "registered_model": next((m.id for m in db.query(ModelVersion).filter(ModelVersion.id.like(f"fl-job-{j.id}-%"))),
                                     None) if db else None}


def _card_path(job_id: int):
    return get_settings().trained_models_dir / f"job-{job_id}.json"


SERVABLE = {"lr": "logistic_regression", "paper_nn": "paper_mlp"}  # architectures backend.app.inference can serve


def registrable(cfg: dict) -> bool:
    """FedBN keeps per-hospital normalisation layers, so it has no single global model to serve."""
    return cfg["model"] in SERVABLE and cfg["algorithm"] != "fedbn"


def model_card(job: TrainingJob, res, pp, clients, hospitals) -> dict:
    """A registry model card for the job's global model, in the format experiments/run_explain.py exports:
    Platt calibration and a Youden threshold on the pooled validation split, OOD ranges and a SHAP background."""
    import numpy as np
    import torch
    from sklearn.linear_model import LogisticRegression

    from fl_engine.data.preprocess import SPECS
    from fl_engine.eval.metrics import THRESHOLD_RULES, operating_point, threshold_free

    cfg, spec = job.config, SPECS["uci_main"]
    model = res.global_model
    Xv = np.vstack([c.X_val for c in clients])
    yv = np.concatenate([c.y_val for c in clients])
    with torch.no_grad():
        pv = torch.sigmoid(model(torch.as_tensor(Xv, dtype=torch.float32))).numpy()
    pv = np.clip(pv, 1e-6, 1 - 1e-6)
    logit = np.log(pv / (1 - pv))
    platt = LogisticRegression(C=1e4).fit(logit.reshape(-1, 1), yv)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    p_cal = 1 / (1 + np.exp(-(a * logit + b)))
    thr = float(THRESHOLD_RULES["youden"](yv, p_cal))
    Xtr = np.vstack([c.X for c in clients])
    bg = Xtr[np.random.default_rng(0).choice(len(Xtr), min(20, len(Xtr)), replace=False)]
    arch = SERVABLE[cfg["model"]]
    privacy = {"mechanism": cfg["privacy"], "note": "see docs/THREAT_MODEL.md"}
    if res.epsilon is not None:
        privacy["epsilon"] = float(res.epsilon)
    return {
        "id": f"fl-job-{job.id}-{arch}", "version": f"job.{job.id}", "name": job.name,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": None,
        "training_method": f"{cfg['algorithm'].upper()} from the training console, {cfg['rounds']} rounds (job #{job.id})",
        "architecture": arch,
        "dataset": f"Federated across {len(hospitals)} hospitals ({', '.join(h.name for h in hospitals)}): uploaded "
                   "datasets plus registered patients with a diagnosis and research consent",
        "target": "angiographic coronary artery disease (num > 0); NOT 4-year incident MI/HF",
        "intended_use": "Research demonstration of privacy-preserving federated learning. Not for clinical decisions.",
        "limitations": ["Trained from the console; not externally validated.",
                        "Calibration and threshold fitted on the pooled validation split of the participating hospitals.",
                        "Hospitals that joined later are not represented."],
        "features": {"spec": "uci_main", "names": list(pp.feature_names_), "numeric": list(spec.numeric),
                     "binary": list(spec.binary), "categorical": {k: list(v) for k, v in spec.categorical.items()},
                     "missing_indicators": list(spec.missing_indicators)},
        "preprocessing": {"scaler": pp.scaler, "impute_numeric": {k: float(v) for k, v in pp.medians_.items()},
                          "impute_mode": {k: float(v) for k, v in pp.modes_.items()},
                          "loc": np.asarray(pp.loc_, dtype=float).tolist(), "scale": np.asarray(pp.scale_, dtype=float).tolist()},
        "weights": {k: v.detach().numpy().tolist() for k, v in model.state_dict().items()},
        "calibration": {"method": "platt", "a": a, "b": b},
        "threshold": {"rule": "youden_on_validation", "value": thr},
        "ood": {"min": Xtr.min(0).tolist(), "max": Xtr.max(0).tolist(), "mean": Xtr.mean(0).tolist(), "std": Xtr.std(0).tolist()},
        "shap_background": bg.tolist(),
        "validation_metrics": {**threshold_free(yv, p_cal), **operating_point(yv, p_cal, thr)},
        "shap_site_consistency_spearman_mean": None,
        "privacy": privacy,
    }


def _run(job_id: int):
    import numpy as np
    from sklearn.model_selection import train_test_split

    from fl_engine.data.federated import fit_federated
    from fl_engine.data.preprocess import SPECS
    from fl_engine.eval.metrics import THRESHOLD_RULES, operating_point, threshold_free
    from fl_engine.sim import Client, FLConfig, run_federated

    db = SessionLocal()
    job = db.get(TrainingJob, job_id)
    try:
        job.status = "running"
        db.commit()
        cfg_d = dict(job.config)
        sites = datasets.training_sites(db)
        if len(sites) < MIN_SITES:
            raise RuntimeError(f"need at least {MIN_SITES} active hospitals with training data, found {len(sites)}")
        splits = {}
        for h, g in sites:
            tr, te = train_test_split(g, test_size=0.2, stratify=g.y, random_state=0)
            itr, va = train_test_split(tr, test_size=0.2, stratify=tr.y, random_state=0)
            splits[h.code] = (itr, va, te)
        scaler = "minmax" if cfg_d["model"] == "lr" else "standard"
        pp = fit_federated([v[0] for v in splits.values()], SPECS["uci_main"], scaler=scaler)
        clients = [Client(s, pp.transform(a), a.y.to_numpy().astype(np.float32), pp.transform(b),
                          b.y.to_numpy().astype(np.float32)) for s, (a, b, _) in splits.items()]
        extra = {}
        if "dpsgd" in cfg_d["privacy"]:
            extra = {"dp_sample_rate": 0.2, "dp_lr": 0.5}  # noise is calibrated to rounds x local_epochs
        cfg = FLConfig(**{**dict(model=cfg_d["model"], algorithm=cfg_d["algorithm"], privacy=cfg_d["privacy"],
                                 rounds=cfg_d["rounds"], local_epochs=cfg_d["local_epochs"], lr=cfg_d["lr"],
                                 batch_size=20000, prox_mu=cfg_d["prox_mu"], dp_epsilon=cfg_d["dp_epsilon"],
                                 class_weight=cfg_d["class_weight"], dropout_prob=cfg_d["dropout_prob"],
                                 eval_every=1), **extra})
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
                       "n_sites": len(splits),
                       **{f"auroc_{k}": v for k, v in per_site.items()}, "wall_seconds": res.wall_seconds,
                       "bytes_down": res.bytes_down, **({"he_" + k: v for k, v in res.he.items()} if res.he else {})}
        job.epsilon = res.epsilon
        job.bytes_up = int(res.bytes_up)
        job.status = "cancelled" if stop.is_set() else "completed"
        job.progress = 1.0 if job.status == "completed" else job.progress
        job.finished_at = datetime.now(timezone.utc)
        if job.status == "completed" and registrable(cfg_d):
            card = model_card(job, res, pp, clients, [h for h, _ in sites])
            out = get_settings().trained_models_dir
            out.mkdir(parents=True, exist_ok=True)
            (out / f"job-{job_id}.json").write_text(json.dumps(card, indent=1))
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
            for n in db.query(FLNode).join(Hospital).filter(Hospital.active.is_(True)).order_by(FLNode.id)]


@router.get("/jobs")
def jobs(_: User = Depends(require(Perm.fl_view)), db: Session = Depends(get_db)):
    return [job_out(j, db) for j in db.query(TrainingJob).order_by(TrainingJob.id.desc()).limit(50)]


@router.get("/jobs/{jid}")
def job(jid: int, _: User = Depends(require(Perm.fl_view)), db: Session = Depends(get_db)):
    j = db.get(TrainingJob, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    return job_out(j, db)


@router.post("/jobs", status_code=201)
def launch(body: JobIn, user: User = Depends(require(Perm.fl_run)), db: Session = Depends(get_db)):
    active = db.query(TrainingJob).filter(TrainingJob.status.in_(["queued", "running"])).count()
    if active >= 3:
        raise HTTPException(429, "too many active jobs; wait for one to finish")
    if (n := len(datasets.training_sites(db))) < MIN_SITES:
        raise HTTPException(409, f"federated training needs at least {MIN_SITES} active hospitals with uploaded "
                                 f"training data; {n} available")
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


@router.post("/jobs/{jid}/register", status_code=201)
def register(jid: int, user: User = Depends(require(Perm.fl_run)), db: Session = Depends(get_db)):
    """Hand a finished job's global model to the registry as a *staging* model. Only the platform admin can
    promote it to production (Model registry), so building and approving a model stay with different people."""
    j = db.get(TrainingJob, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    path = _card_path(jid)
    if j.status != "completed" or not path.exists():
        raise HTTPException(409, "only a completed LR or paper-NN job without FedBN can be registered")
    card = json.loads(path.read_text())
    if db.get(ModelVersion, card["id"]):
        raise HTTPException(409, "this job's model is already registered")
    mv = ModelVersion(id=card["id"], version=card["version"], name=card["name"][:200], stage="staging",
                      sha256=hashlib.sha256(path.read_bytes()).hexdigest(), path=str(path))
    db.add(mv)
    db.commit()
    audit.log(db, "model.register", user=user, resource=f"model:{mv.id}", detail={"job": jid, "sha256": mv.sha256})
    return job_out(j, db)
