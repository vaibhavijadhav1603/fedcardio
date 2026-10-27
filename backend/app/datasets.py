"""Hospital training datasets: CSV validation, encrypted storage and loading for FL jobs.

A hospital's training rows are its uploaded CSV (UCI Heart schema, validated, normalised and stored
envelope-encrypted with the hospital's own KEK, like patient records) plus its registered patients
who have a diagnosis on record and an active research consent. Only the FL worker decrypts them,
inside that hospital's simulated client.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from .crypto import decrypt_payload, encrypt_payload
from .fhir import features_from_bundle
from .models import Consent, FLNode, Hospital, HospitalDataset, Patient, User, utcnow

FEATURES = ["age", "sex", "cp", "trestbps", "chol", "fbs", "restecg", "thalach", "exang", "oldpeak"]
TARGETS = ("target", "num", "y")  # num > 0 is the UCI binarisation
# column -> (allowed values or (min, max), may be missing)
RULES: dict[str, tuple[tuple, bool]] = {
    "age": ((1, 120), False),
    "sex": ({0, 1}, False),
    "cp": ({1, 2, 3, 4}, True),
    "trestbps": ((50, 250), True),
    "chol": ((50, 700), True),
    "fbs": ({0, 1}, True),
    "restecg": ({0, 1, 2}, True),
    "thalach": ((40, 250), True),
    "exang": ({0, 1}, True),
    "oldpeak": ((-5, 10), True),
}
MAX_BYTES = 5_000_000
MAX_ROWS = 100_000
MIN_ROWS = 30
MIN_PER_CLASS = 5
TEMPLATE = (",".join(FEATURES + ["target"]) + "\n"
            "63,1,1,145,233,1,2,150,0,2.3,0\n"
            "67,1,4,160,286,0,2,108,1,1.5,1\n"
            "41,0,2,130,,0,2,172,0,1.4,0\n")


class DatasetError(ValueError):
    pass


def parse_csv(text: str) -> pd.DataFrame:
    """Validate an uploaded CSV and return it in the engine's schema (FEATURES + y)."""
    if len(text.encode()) > MAX_BYTES:
        raise DatasetError(f"file is larger than {MAX_BYTES // 1_000_000} MB")
    try:
        df = pd.read_csv(io.StringIO(text), na_values=["?", ""], skipinitialspace=True)
    except Exception as e:  # noqa: BLE001 - any parser error is a user error here
        raise DatasetError(f"could not read CSV: {e}") from e
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in FEATURES if c not in df.columns]
    target = next((t for t in TARGETS if t in df.columns), None)
    if missing or target is None:
        need = missing + ([] if target else ["target"])
        raise DatasetError(f"missing columns: {', '.join(need)}")
    if len(df) > MAX_ROWS:
        raise DatasetError(f"more than {MAX_ROWS} rows")
    out = pd.DataFrame(index=df.index)
    errors: list[str] = []
    for col in FEATURES + [target]:
        v = pd.to_numeric(df[col], errors="coerce")
        bad = v.isna() & df[col].notna()
        errors += [f"line {i + 2}: {col} is not a number" for i in df.index[bad][:3]]
        out[col] = v
    if errors:
        raise DatasetError("; ".join(errors[:10]))
    # 0 means "not recorded" for these in the UCI files (see fl_engine.data.loaders)
    out["chol"] = out["chol"].replace(0, np.nan)
    out["trestbps"] = out["trestbps"].replace(0, np.nan)
    for col, (allowed, nullable) in RULES.items():
        v = out[col]
        if not nullable:
            errors += [f"line {i + 2}: {col} is empty" for i in out.index[v.isna()][:3]]
        ok = v.isna() | (v.between(*allowed) if isinstance(allowed, tuple) else v.isin(allowed))
        errors += [f"line {i + 2}: {col}={v[i]:g} is out of range" for i in out.index[~ok][:3]]
    t = out[target]
    if t.isna().any() or not t.isin(range(5) if target == "num" else (0, 1)).all():
        errors.append(f"{target} must be {'0-4' if target == 'num' else '0 or 1'} on every row")
    if errors:
        raise DatasetError("; ".join(errors[:10]))
    out["y"] = (t > 0).astype(int)
    out = out.drop(columns=[target]).reset_index(drop=True)
    pos = int(out.y.sum())
    if len(out) < MIN_ROWS or min(pos, len(out) - pos) < MIN_PER_CLASS:
        raise DatasetError(f"need at least {MIN_ROWS} rows and {MIN_PER_CLASS} patients with and without disease "
                           f"(got {len(out)} rows, {pos} with disease)")
    return out


def store(db: Session, hospital: Hospital, df: pd.DataFrame, filename: str, user: User | None) -> HospitalDataset:
    """Replace the hospital's dataset and bring its FL node online. Caller commits."""
    raw = df.to_csv(index=False).encode()
    ct, nonce, wdek = encrypt_payload(hospital.code, raw, _aad(hospital))
    ds = db.query(HospitalDataset).filter_by(hospital_id=hospital.id).first() or HospitalDataset(hospital_id=hospital.id)
    ds.filename, ds.n_rows, ds.n_positive = filename[:200], len(df), int(df.y.sum())
    ds.sha256, ds.ciphertext, ds.nonce, ds.wrapped_dek = hashlib.sha256(raw).hexdigest(), ct, nonce, wdek
    ds.uploaded_by, ds.uploaded_at = user.id if user else None, utcnow()
    db.add(ds)
    db.flush()
    refresh_node(db, hospital, commit=False)
    return ds


def load(ds: HospitalDataset) -> pd.DataFrame:
    raw = decrypt_payload(ds.hospital.code, ds.wrapped_dek, ds.nonce, ds.ciphertext, _aad(ds.hospital))
    return pd.read_csv(io.BytesIO(raw))


def patient_rows(db: Session, hospital: Hospital) -> pd.DataFrame:
    """Registered patients who can be training rows: a confirmed or ruled-out diagnosis on record AND an
    active research consent (federated training is research use). Decrypted only here, inside the node."""
    now = utcnow()
    consented = {c.patient_id for c in db.query(Consent).join(Patient).filter(
        Patient.hospital_id == hospital.id, Consent.purpose == "research", Consent.revoked_at.is_(None))
        if (c.valid_until if c.valid_until.tzinfo else c.valid_until.replace(tzinfo=timezone.utc)) > now}
    rows = []
    for p in db.query(Patient).filter(Patient.id.in_(consented)):
        raw = decrypt_payload(hospital.code, p.wrapped_dek, p.nonce, p.ciphertext, p.pseudo_id.encode())
        f = features_from_bundle(json.loads(raw))
        if f.get("diagnosis") is None:
            continue
        row = {k: f.get(k, np.nan) for k in FEATURES}
        row["age"], row["y"] = now.year - f["birth_year"], int(f["diagnosis"])
        rows.append(row)
    df = pd.DataFrame(rows, columns=FEATURES + ["y"]).astype(float)
    ok = pd.Series(True, index=df.index)  # same plausibility rules as an uploaded CSV
    for col, (allowed, _) in RULES.items():
        v = df[col]
        ok &= v.isna() | (v.between(*allowed) if isinstance(allowed, tuple) else v.isin(allowed))
    return df[ok].reset_index(drop=True)


def hospital_frame(db: Session, hospital: Hospital) -> tuple[pd.DataFrame, int, int]:
    """(training rows, rows from the uploaded CSV, rows from registered patients)."""
    ds = db.query(HospitalDataset).filter_by(hospital_id=hospital.id).first()
    csv = load(ds) if ds else pd.DataFrame(columns=FEATURES + ["y"])
    pts = patient_rows(db, hospital)
    return pd.concat([csv, pts], ignore_index=True), len(csv), len(pts)


def usable(df: pd.DataFrame) -> bool:
    pos = int(df.y.sum()) if len(df) else 0
    return len(df) >= MIN_ROWS and min(pos, len(df) - pos) >= MIN_PER_CLASS


def refresh_node(db: Session, hospital: Hospital, commit: bool = True) -> None:
    """Keep the hospital's FL node in step with how much training data it holds."""
    df, _, _ = hospital_frame(db, hospital)
    node = db.query(FLNode).filter_by(hospital_id=hospital.id).first()
    if node is None and len(df):
        node = FLNode(hospital_id=hospital.id, name=f"fl-client-{hospital.code}",
                      cert_fingerprint="SHA256:" + hashlib.sha256(hospital.code.encode()).hexdigest()[:32])
        db.add(node)
    if node is not None:
        node.status = ("online" if usable(df) else "no data" if not len(df) else "too few") if hospital.active else "offline"
        node.n_records, node.last_seen = len(df), utcnow()
    if commit:
        db.commit()


def training_sites(db: Session) -> list[tuple[Hospital, pd.DataFrame]]:
    """Active hospitals with enough training data, in a stable order: these are the FL clients of a job."""
    out = []
    for h in db.query(Hospital).filter(Hospital.active.is_(True)).order_by(Hospital.id):
        df, _, _ = hospital_frame(db, h)
        if usable(df):
            out.append((h, df))
    return out


def summary(ds: HospitalDataset | None) -> dict | None:
    if ds is None:
        return None
    return {"filename": ds.filename, "n_rows": ds.n_rows, "n_positive": ds.n_positive, "sha256": ds.sha256,
            "uploaded_at": iso_utc(ds.uploaded_at)}


def iso_utc(dt: datetime | None) -> str | None:
    """SQLite returns naive datetimes; they are UTC, so say so (else browsers read them as local time)."""
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _aad(h: Hospital) -> bytes:
    return f"dataset:{h.code}".encode()
