"""Seed the database with demo hospitals, users, synthetic patients and registry models.

Patients are built from the public UCI Heart Disease rows of each hospital, with generated
names, and each hospital's UCI rows become its encrypted training dataset. No real identifiable
data. Demo password for every account: see DEMO_PASSWORD (dev only).

python -m backend.app.seed [--reset] [--no-demo]

--no-demo creates only the platform-level accounts (platform admin, auditor, data scientist) and the
model registry, so a platform admin can add their own hospitals and each hospital admin uploads data.
Running it on an already-seeded database backfills missing demo training datasets, gives every active
hospital without one a demo admin and clinician, and re-enables detached platform-level demo accounts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone

import numpy as np

from . import datasets
from .audit import log
from .config import get_settings
from .db import Base, SessionLocal, add_missing_sqlite_columns, engine
from .models import (
    Consent,
    Hospital,
    HospitalDataset,
    ModelVersion,
    Patient,
    Role,
    User,
)
from .routers.patients import create_patient_record
from .security import hash_password

DEMO_PASSWORD = get_settings().demo_password
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


def _uci():
    try:
        from fl_engine.data.loaders import load_uci_heart
        return load_uci_heart()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"UCI data missing; run `python -m fl_engine.data.download` first ({e})") from e


def _site_frame(df, code):
    return df.loc[df.site == code, datasets.FEATURES + ["y"]].reset_index(drop=True)


def backfill_datasets(db) -> int:
    """Give demo hospitals seeded before datasets existed their UCI training data."""
    demo = {code for code, _, _ in HOSPITALS}
    todo = [h for h in db.query(Hospital).filter(Hospital.code.in_(demo))
            if not db.query(HospitalDataset).filter_by(hospital_id=h.id).first()]
    if todo:
        df = _uci()
        for h in todo:
            datasets.store(db, h, _site_frame(df, h.code), f"uci_{h.code}.csv", None)
        db.commit()
    return len(todo)


def backfill_accounts(db) -> list[str]:
    """Dev only: every active hospital gets a demo admin and a demo clinician if it has none, and
    platform-level demo accounts that a hospital deletion detached are enabled again."""
    pw = hash_password(DEMO_PASSWORD)
    made = []
    for h in db.query(Hospital).filter(Hospital.active.is_(True)).order_by(Hospital.id):
        for role, email, name in ((Role.hospital_admin, f"admin.{h.code}@fedcardio.dev", f"{h.name} Admin"),
                                  (Role.clinician, f"dr.{h.code}@fedcardio.dev", f"Dr. {h.name}")):
            if db.query(User).filter_by(hospital_id=h.id, role=role).first() or db.query(User).filter_by(email=email).first():
                continue
            db.add(User(email=email, full_name=name, role=role, hospital_id=h.id, password_hash=pw))
            made.append(email)
    for u in db.query(User).filter(User.role.in_([Role.data_scientist, Role.auditor]), User.active.is_(False),
                                   User.hospital_id.is_(None), User.email.like("%@fedcardio.dev")):
        u.active = True
        made.append(f"{u.email} (re-enabled)")
    db.commit()
    return made


STAFF = {"cleveland": ("Dr. Asha Rao", "Maya Admin"), "hungarian": ("Dr. Péter Nagy", "Anna Admin"),
         "switzerland": ("Dr. Lea Keller", "Jonas Admin"), "va_long_beach": ("Dr. Omar Silva", "Sara Admin")}


def add_demo_hospitals(db, codes, patients_per_site: int = 40) -> list[Hospital]:
    """Create the given demo hospitals with their admin, clinician, consented patients and UCI training data."""
    if not codes:
        return []
    rnd = random.Random(7)
    pw = hash_password(DEMO_PASSWORD)
    df = _uci()
    now_year = datetime.now(timezone.utc).year
    taken = {n for (n,) in db.query(Patient.display_name)}
    names_pool = [f"{a} {b}" for a in FIRST for b in LAST]
    rnd.shuffle(names_pool)  # unique synthetic names, also across hospitals already present
    names_pool = [n for n in names_pool if n not in taken]
    made = []
    for code, name, city in HOSPITALS:
        if code not in codes:
            continue
        h = Hospital(code=code, name=name, city=city)
        db.add(h)
        db.flush()
        dr_name, admin_name = STAFF[code]
        dr = User(email=f"dr.{code}@fedcardio.dev", full_name=dr_name, role=Role.clinician, hospital_id=h.id, password_hash=pw)
        db.add_all([dr, User(email=f"admin.{code}@fedcardio.dev", full_name=admin_name, role=Role.hospital_admin,
                             hospital_id=h.id, password_hash=pw)])
        db.flush()
        g = df[df.site == code].sample(n=min(patients_per_site, (df.site == code).sum()), random_state=1)
        datasets.store(db, h, _site_frame(df, code), f"uci_{code}.csv", None)  # also brings its FL node online
        for i, (_, r) in enumerate(g.iterrows()):
            feats = {k: float(r[k]) for k in ("trestbps", "chol", "thalach", "oldpeak", "fbs", "exang", "cp", "restecg")
                     if not np.isnan(r[k])}
            p = create_patient_record(db, h, f"{code}-{i:04d}", names_pool.pop(),
                                      "male" if r["sex"] == 1 else "female", int(now_year - r["age"]), feats)
            if i % 2 == 0:
                db.add(Consent(patient_id=p.id, purpose=rnd.choice(["treatment", "care_coordination"]),
                               valid_until=datetime.now(timezone.utc) + timedelta(days=365), recorded_by=dr.id))
        made.append(h)
    return made


def restore_demo(db) -> list[str]:
    """Bring back demo hospitals that were deleted (a deactivated one is re-activated from the Admin page instead)."""
    have = {c for (c,) in db.query(Hospital.code)}
    missing = [code for code, _, _ in HOSPITALS if code not in have
               and not db.query(User).filter(User.email.in_([f"dr.{code}@fedcardio.dev", f"admin.{code}@fedcardio.dev"])).first()]
    made = add_demo_hospitals(db, missing)
    db.commit()
    for h in made:
        log(db, "hospital.restore_demo", resource=f"hospital:{h.id}", detail={"code": h.code})
    return [h.name for h in made]


def seed(reset: bool = False, patients_per_site: int = 40, demo: bool = True, restore: bool = False):
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    add_missing_sqlite_columns()
    db = SessionLocal()
    if db.query(User).count():
        if restore:
            for name in restore_demo(db):
                print(f"restored demo hospital: {name}")
        n = backfill_datasets(db)
        made = backfill_accounts(db)
        print("already seeded" + (f"; added training data for {n} demo hospitals" if n else "")
              + "".join(f"\n  account: {m}" for m in made))
        return
    pw = hash_password(DEMO_PASSWORD)

    def user(email, name, role, hosp=None):
        u = User(email=email, full_name=name, role=role, hospital_id=hosp.id if hosp else None, password_hash=pw)
        db.add(u)
        return u

    user("admin@fedcardio.dev", "Platform Admin", Role.platform_admin)
    user("auditor@fedcardio.dev", "Ines Auditor", Role.auditor)
    user("ds@fedcardio.dev", "Kenji Data Scientist", Role.data_scientist)  # platform-level: sees no hospital's data
    db.flush()
    hs = add_demo_hospitals(db, [code for code, _, _ in HOSPITALS] if demo else [], patients_per_site)
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
    log(db, "system.seed", detail={"hospitals": len(hs), "patients_per_site": patients_per_site if demo else 0})
    print(f"seeded {len(hs)} hospitals, {db.query(User).count()} users, {db.query(Patient).count()} patients, "
          f"{db.query(ModelVersion).count()} models")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-demo", action="store_true", help="no demo hospitals, clinicians or patients")
    ap.add_argument("--restore-demo", action="store_true", help="re-create demo hospitals that were deleted")
    a = ap.parse_args()
    seed(a.reset, demo=not a.no_demo, restore=a.restore_demo)
