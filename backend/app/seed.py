"""Seed the database with demo hospitals, users, synthetic patients and registry models.

Patients are built from the public UCI Heart Disease rows of each hospital, with generated
names. No real identifiable data. Demo password for every account: see DEMO_PASSWORD (dev only).

python -m backend.app.seed [--reset]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone

import numpy as np

from .audit import log
from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import Consent, FLNode, Hospital, ModelVersion, Patient, Role, User
from .routers.patients import create_patient_record
from .security import hash_password

DEMO_PASSWORD = "FedCardio!2026"
HOSPITALS = [
    ("cleveland", "Cleveland Clinic Foundation", "Cleveland, OH"),
    ("hungarian", "Hungarian Institute of Cardiology", "Budapest"),
    ("switzerland", "University Hospital Zürich & Basel", "Zürich"),
    ("va_long_beach", "VA Medical Center Long Beach", "Long Beach, CA"),
]
FIRST = ["Asha", "Ravi", "Meera", "Arjun", "Elena", "Tom", "Sara", "Luca", "Nina", "Omar", "Priya", "Jonas",
         "Hana", "Mateo", "Leah", "Ivan", "Zara", "Kenji", "Anya", "Felix", "Maya", "Noah", "Ines", "Karim"]
LAST = ["Kumar", "Novak", "Rossi", "Meyer", "Silva", "Horvath", "Patel", "Keller", "Moreau", "Kowalski",
        "Nagy", "Fischer", "Rao", "Weber", "Costa", "Bauer", "Iyer", "Varga", "Lopez", "Schmidt"]


def seed(reset: bool = False, patients_per_site: int = 40):
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.query(Hospital).count():
        print("already seeded")
        return
    rnd = random.Random(7)
    hs = {}
    for code, name, city in HOSPITALS:
        h = Hospital(code=code, name=name, city=city)
        db.add(h)
        hs[code] = h
    db.flush()
    pw = hash_password(DEMO_PASSWORD)

    def user(email, name, role, hosp=None):
        u = User(email=email, full_name=name, role=role, hospital_id=hosp.id if hosp else None, password_hash=pw)
        db.add(u)
        return u

    user("admin@fedcardio.dev", "Platform Admin", Role.platform_admin)
    user("auditor@fedcardio.dev", "Ines Auditor", Role.auditor)
    user("ds@fedcardio.dev", "Kenji Data Scientist", Role.data_scientist, hs["cleveland"])
    names = {"cleveland": ("Dr. Asha Rao", "Maya Admin"), "hungarian": ("Dr. Péter Nagy", "Anna Admin"),
             "switzerland": ("Dr. Lea Keller", "Jonas Admin"), "va_long_beach": ("Dr. Omar Silva", "Sara Admin")}
    for code, h in hs.items():
        user(f"dr.{code}@fedcardio.dev", names[code][0], Role.clinician, h)
        user(f"admin.{code}@fedcardio.dev", names[code][1], Role.hospital_admin, h)
    db.flush()

    try:
        from fl_engine.data.loaders import load_uci_heart
        df = load_uci_heart()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"UCI data missing; run `python -m fl_engine.data.download` first ({e})") from e
    now_year = datetime.now(timezone.utc).year
    names_pool = [f"{a} {b}" for a in FIRST for b in LAST]
    rnd.shuffle(names_pool)  # unique synthetic names
    clinicians = {u.hospital_id: u for u in db.query(User).filter_by(role=Role.clinician)}
    for code, h in hs.items():
        g = df[df.site == code].sample(n=min(patients_per_site, (df.site == code).sum()), random_state=1)
        db.add(FLNode(hospital_id=h.id, name=f"fl-client-{code}", status="online",
                      n_records=int((df.site == code).sum()),
                      cert_fingerprint="SHA256:" + hashlib.sha256(code.encode()).hexdigest()[:32]))
        for i, (_, r) in enumerate(g.iterrows()):
            feats = {k: float(r[k]) for k in ("trestbps", "chol", "thalach", "oldpeak", "fbs", "exang", "cp", "restecg")
                     if not np.isnan(r[k])}
            p = create_patient_record(db, h, f"{code}-{i:04d}", names_pool.pop(),
                                      "male" if r["sex"] == 1 else "female", int(now_year - r["age"]), feats)
            if i % 2 == 0:
                db.add(Consent(patient_id=p.id, purpose=rnd.choice(["treatment", "care_coordination"]),
                               valid_until=datetime.now(timezone.utc) + timedelta(days=365),
                               recorded_by=clinicians[h.id].id))
    reg = get_settings().registry_dir
    first = True
    for path in sorted(reg.glob("*/model.json")):
        card = json.loads(path.read_text())
        db.add(ModelVersion(id=card["id"], version=card["version"], name=card["name"],
                            stage="production" if first else "staging",
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), path=str(path),
                            promoted_at=datetime.now(timezone.utc) if first else None))
        first = False
    db.commit()
    log(db, "system.seed", detail={"hospitals": len(hs), "patients_per_site": patients_per_site})
    print(f"seeded {len(hs)} hospitals, {db.query(User).count()} users, {db.query(Patient).count()} patients, "
          f"{db.query(ModelVersion).count()} models")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    seed(ap.parse_args().reset)
