"""Model serving, model registry, results explorer and audit endpoints."""
from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..fhir import features_from_bundle
from ..inference import FIELD_META, load_model
from ..models import AuditEvent, ModelVersion, Patient, User
from ..security import Perm, require
from .patients import _own, _record

router = APIRouter(tags=["ml"])


def _clean(o):
    """JSON-safe: NaN/inf -> None."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


# ------------------------------------------------------------------ prediction
def production_model(db: Session) -> ModelVersion:
    mv = db.query(ModelVersion).filter_by(stage="production").order_by(ModelVersion.promoted_at.desc()).first()
    if mv is None:
        raise HTTPException(503, "no production model")
    return mv


class PredictIn(BaseModel):
    patient_id: int | None = None
    features: dict[str, float | None] = Field(default_factory=dict)


@router.get("/predict/schema")
def predict_schema(_: User = Depends(require(Perm.predict))):
    return {"fields": [{"key": k, **v} for k, v in FIELD_META.items()]}


@router.post("/predict")
def predict(body: PredictIn, user: User = Depends(require(Perm.predict)), db: Session = Depends(get_db)):
    unknown = set(body.features) - set(FIELD_META)
    if unknown:
        raise HTTPException(422, f"unknown features {sorted(unknown)}")
    raw = dict(body.features)
    resource = "adhoc"
    if body.patient_id is not None:
        p = db.get(Patient, body.patient_id)
        if p is None:
            raise HTTPException(404, "patient not found")
        _own(user, p)
        rec = features_from_bundle(_record(p))
        rec["age"] = datetime.now(timezone.utc).year - rec.pop("birth_year")
        raw = {**rec, **{k: v for k, v in raw.items() if v is not None}}
        resource = f"patient:{p.pseudo_id}"
    for k, meta in FIELD_META.items():
        v = raw.get(k)
        if v is not None and meta["kind"] == "number" and not (meta["min"] - 1e-9 <= v <= meta["max"] + 1e-9):
            raise HTTPException(422, f"{meta['label']} must be between {meta['min']} and {meta['max']}")
    mv = production_model(db)
    out = load_model(mv.path).predict(raw)
    audit.log(db, "model.predict", user=user, resource=resource,
              detail={"model": mv.id, "probability": round(out["probability"], 4), "decision": out["decision"],
                      "ood": out["ood_warning"]})
    return _clean({**out, "inputs": raw,
                   "disclaimer": "Research prototype. Not validated for clinical use; do not use for patient care decisions."})


# ------------------------------------------------------------------ model registry
def _card(mv: ModelVersion) -> dict:
    card = json.loads(Path(mv.path).read_text())
    for k in ("weights", "shap_background", "ood"):
        card.pop(k, None)
    return card


def mv_out(mv: ModelVersion, with_card=False) -> dict:
    out = {"id": mv.id, "version": mv.version, "name": mv.name, "stage": mv.stage, "sha256": mv.sha256,
           "created_at": mv.created_at.isoformat(), "promoted_at": mv.promoted_at and mv.promoted_at.isoformat()}
    if with_card:
        out["card"] = _card(mv)
    return out


@router.get("/models")
def list_models(_: User = Depends(require(Perm.model_view)), db: Session = Depends(get_db)):
    return [_clean(mv_out(m, with_card=True)) for m in db.query(ModelVersion).order_by(ModelVersion.created_at.desc())]


@router.get("/models/{mid}")
def get_model(mid: str, _: User = Depends(require(Perm.model_view)), db: Session = Depends(get_db)):
    mv = db.get(ModelVersion, mid)
    if mv is None:
        raise HTTPException(404, "model not found")
    return _clean(mv_out(mv, with_card=True))


@router.post("/models/{mid}/promote")
def promote(mid: str, user: User = Depends(require(Perm.model_promote)), db: Session = Depends(get_db)):
    mv = db.get(ModelVersion, mid)
    if mv is None:
        raise HTTPException(404, "model not found")
    prev = [m.id for m in db.query(ModelVersion).filter_by(stage="production") if m.id != mid]
    for m in db.query(ModelVersion).filter_by(stage="production"):
        m.stage = "archived"
    mv.stage, mv.promoted_at = "production", datetime.now(timezone.utc)
    db.commit()
    audit.log(db, "model.promote", user=user, resource=f"model:{mid}", detail={"replaced": prev})
    return mv_out(mv)


@router.post("/models/{mid}/rollback")
def rollback(mid: str, user: User = Depends(require(Perm.model_promote)), db: Session = Depends(get_db)):
    """Archive this production model and restore the most recently promoted archived one."""
    mv = db.get(ModelVersion, mid)
    if mv is None or mv.stage != "production":
        raise HTTPException(409, "only the production model can be rolled back")
    prev = (db.query(ModelVersion).filter(ModelVersion.stage == "archived", ModelVersion.promoted_at.isnot(None))
            .order_by(ModelVersion.promoted_at.desc()).first())
    if prev is None:
        raise HTTPException(409, "no previous production model to restore")
    mv.stage = "archived"
    prev.stage, prev.promoted_at = "production", datetime.now(timezone.utc)
    db.commit()
    audit.log(db, "model.rollback", user=user, resource=f"model:{mid}", detail={"restored": prev.id})
    return mv_out(prev)


# ------------------------------------------------------------------ results explorer
def _summ(df: pd.DataFrame, by: list[str], policy="val_youden") -> list[dict]:
    if "policy" in df:
        df = df[df.policy == policy]
    metrics = [c for c in ("auroc", "auprc", "brier", "brier_platt", "ece", "ece_platt", "sensitivity", "specificity",
                           "ppv", "npv", "f1", "site_mean_auroc", "worst_site_auroc", "bytes_up", "wall_seconds",
                           "epsilon") if c in df]
    rows = []
    for key, g in df.groupby(by, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        r = dict(zip(by, key))
        r["k"] = len(g)
        ratio = float((g.n_test / g.n_train.replace(0, np.nan)).mean()) if "n_test" in g and "n_train" in g else 0.25
        ratio = ratio if np.isfinite(ratio) else 0.25
        for m in metrics:
            x = g[m].astype(float).dropna().to_numpy()
            if len(x) == 0:
                continue
            mean = float(x.mean())
            r[m] = mean
            if len(x) > 1:
                from scipy import stats
                se = float(np.sqrt((1 / len(x) + ratio) * x.var(ddof=1)))
                h = float(stats.t.ppf(0.975, len(x) - 1) * se)
                r[f"{m}_lo"], r[f"{m}_hi"] = mean - h, mean + h
        rows.append(r)
    return rows


@router.get("/results/summary")
def results_summary(_: User = Depends(require(Perm.results_view))):
    d = get_settings().results_dir
    out: dict = {"available": sorted(p.name for p in d.glob("*.csv"))}

    def read(name):
        p = d / name
        return pd.read_csv(p) if p.exists() else None

    if (u := read("p2_uci_folds.csv")) is not None:
        out["uci"] = sorted(_summ(u, ["method", "paper_reimpl"]), key=lambda r: -r.get("auroc", 0))
        out["uci_policies"] = [{**x, "policy": pol} for pol in ("val_youden", "val_sens80", "fixed_0.5", "insample_youden")
                               for x in _summ(u, ["method"], policy=pol)]
    if (s := read("p2_uci_persite.csv")) is not None:
        out["uci_sites"] = _summ(s, ["method", "site"], policy=None)
    if (h := read("p2_uci_history.csv")) is not None:
        out["uci_history"] = h[["method", "round", "val_auroc"]].to_dict("records")
    if (n := read("p2_noniid_folds.csv")) is not None:
        out["noniid"] = _summ(n.assign(alpha=n.alpha.astype(str)), ["method", "alpha"])
    if (c := read("p2_clients_folds.csv")) is not None:
        out["clients"] = _summ(c, ["n_clients", "dropout"])
    if (pv := read("p2_privacy_folds.csv")) is not None:
        out["privacy"] = _summ(pv, ["method"])
    if (im := read("p2_imbalance_folds.csv")) is not None:
        out["imbalance"] = [{**x, "policy": pol} for pol in ("val_youden", "val_sens80", "fixed_0.5", "insample_youden")
                            for x in _summ(im, ["method"], policy=pol)]
    if (a := read("p2_attacks.csv")) is not None:
        out["attacks"] = a.groupby(["attack", "mechanism"]).agg(
            relative_error=("relative_error", "mean"), attack_auc=("attack_auc", "mean")).reset_index().to_dict("records")
    if (f := read("p2_fairness.csv")) is not None:
        out["fairness"] = f.to_dict("records")
    if (sh := read("p2_shap_sites.csv")) is not None:
        out["shap"] = sh.to_dict("records")
    for name in ("p1_uci_folds.csv", "p1_cardio_folds.csv", "p1_cardio_lowprev_folds.csv"):
        if (p1 := read(name)) is not None:
            out[name.replace("_folds.csv", "")] = _summ(p1, ["model"])
    out["paper_table2"] = [
        {"method": m, "learner": lr, "auroc": a, "sensitivity": se, "specificity": sp}
        for m, lr, a, se, sp in [("cML", "NN", .672, .166, .909), ("cML", "LR", .670, .205, .899),
                                 ("FedAvg", "NN", .680, .184, .897), ("FedAvg", "LR", .663, .204, .892),
                                 ("FedAvg_DP", "NN", .657, .079, .896), ("FedAvg_DP", "LR", .623, .018, .988),
                                 ("FedAvg_HE", "NN", .686, .190, .901), ("FedAvg_HE", "LR", .664, .205, .893)]]
    return _clean(out)


@router.get("/results/files/{name}")
def results_file(name: str, user: User = Depends(require(Perm.results_view))):
    d = get_settings().results_dir.resolve()
    p = (d / name).resolve()
    if p.parent != d or p.suffix not in (".csv", ".md", ".json") or not p.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(p, filename=p.name)


# ------------------------------------------------------------------ audit
def ev_out(e: AuditEvent) -> dict:
    return {"seq": e.seq, "ts": e.ts.isoformat(), "actor_email": e.actor_email, "actor_role": e.actor_role,
            "hospital_id": e.hospital_id, "action": e.action, "resource": e.resource, "outcome": e.outcome,
            "detail": e.detail, "hash": e.hash, "prev_hash": e.prev_hash}


def _audit_query(db, user, action, actor, outcome):
    q = db.query(AuditEvent)
    if user.role.value == "hospital_admin":
        q = q.filter(AuditEvent.hospital_id == user.hospital_id)
    if action:
        q = q.filter(AuditEvent.action.like(f"{action}%"))
    if actor:
        q = q.filter(AuditEvent.actor_email.ilike(f"%{actor}%"))
    if outcome:
        q = q.filter(AuditEvent.outcome == outcome)
    return q.order_by(AuditEvent.seq.desc())


@router.get("/audit")
def list_audit(action: str = Query("", max_length=60), actor: str = Query("", max_length=200),
               outcome: str = Query("", max_length=20), limit: int = Query(100, le=1000), offset: int = 0,
               user: User = Depends(require(Perm.audit_view)), db: Session = Depends(get_db)):
    q = _audit_query(db, user, action, actor, outcome)
    return {"total": q.count(), "items": [ev_out(e) for e in q.offset(offset).limit(limit)]}


@router.get("/audit/verify")
def verify(user: User = Depends(require(Perm.audit_view)), db: Session = Depends(get_db)):
    return audit.verify_chain(db)


@router.get("/audit/export.csv")
def export_audit(action: str = "", actor: str = "", outcome: str = "",
                 user: User = Depends(require(Perm.audit_export)), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "ts", "actor_email", "actor_role", "hospital_id", "action", "resource", "outcome", "detail", "hash"])
    for e in _audit_query(db, user, action, actor, outcome):
        w.writerow([e.seq, e.ts.isoformat(), e.actor_email, e.actor_role, e.hospital_id, e.action, e.resource,
                    e.outcome, json.dumps(e.detail), e.hash])
    audit.log(db, "audit.export", user=user)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=audit_log.csv"})
