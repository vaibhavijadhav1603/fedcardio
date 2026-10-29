"""Patients, consent and inter-hospital record sharing (synthetic/public data only)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import audit, datasets
from ..crypto import decrypt_payload, encrypt_payload, pseudonymize, rewrap
from ..db import get_db
from ..fhir import consent_resource, features_from_bundle, patient_bundle
from ..models import Consent, Hospital, Patient, ShareRequest, ShareStatus, User
from ..security import Perm, current_user, has_perm, require

router = APIRouter(tags=["patients"])
PURPOSES = ("treatment", "care_coordination", "research")


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _own(user: User, p: Patient):
    if p.hospital_id != user.hospital_id:
        raise HTTPException(404, "patient not found")  # do not reveal existence across tenants


def _record(p: Patient, wrapped=None, tenant=None) -> dict:
    tenant = tenant or p.hospital.code
    raw = decrypt_payload(tenant, wrapped or p.wrapped_dek, p.nonce, p.ciphertext, p.pseudo_id.encode())
    return json.loads(raw)


def patient_summary(p: Patient) -> dict:
    return {"id": p.id, "pseudo_id": p.pseudo_id, "display_name": p.display_name, "sex": p.sex,
            "birth_year": p.birth_year, "age": _now().year - p.birth_year, "hospital_id": p.hospital_id,
            "hospital_name": p.hospital.name, "created_at": p.created_at.isoformat()}


def create_patient_record(db: Session, hospital: Hospital, local_id: str, name: str, sex: str, birth_year: int,
                          features: dict, diagnosis: int | None = None) -> Patient:
    pid = pseudonymize(hospital.code, local_id)
    bundle = patient_bundle(pid, sex, birth_year, features, hospital.code, diagnosis)
    ct, nonce, wdek = encrypt_payload(hospital.code, json.dumps(bundle).encode(), pid.encode())
    p = Patient(pseudo_id=pid, hospital_id=hospital.id, display_name=name, sex=sex, birth_year=birth_year,
                ciphertext=ct, nonce=nonce, wrapped_dek=wdek)
    db.add(p)
    db.flush()
    return p


# ------------------------------------------------------------------ patients
@router.get("/patients")
def list_patients(q: str = Query("", max_length=80), limit: int = Query(50, le=200),
                  user: User = Depends(require(Perm.patient_read)), db: Session = Depends(get_db)):
    qry = db.query(Patient).filter(Patient.hospital_id == user.hospital_id)
    if q:
        like = f"%{q}%"
        qry = qry.filter(or_(Patient.display_name.ilike(like), Patient.pseudo_id.ilike(like)))
    return [patient_summary(p) for p in qry.order_by(Patient.display_name).limit(limit)]


@router.get("/patients/directory")
def directory(pseudo_id: str = Query(min_length=6, max_length=40), user: User = Depends(require(Perm.share_request)),
              db: Session = Depends(get_db)):
    """Cross-hospital lookup by exact pseudonym; reveals only where the record lives, never its content."""
    p = db.query(Patient).filter(Patient.pseudo_id == pseudo_id.strip().upper()).first()
    if p is None or p.hospital_id == user.hospital_id or not p.hospital.active:
        raise HTTPException(404, "no external record with that pseudonym")
    audit.log(db, "patient.directory_lookup", user=user, resource=f"patient:{p.pseudo_id}")
    return {"pseudo_id": p.pseudo_id, "hospital_id": p.hospital_id, "hospital_name": p.hospital.name}


@router.get("/patients/match")
def match(name: str = Query(min_length=3, max_length=120), birth_year: int = Query(ge=1900),
          sex: str = Query(pattern="^(male|female)$"), user: User = Depends(require(Perm.share_request)),
          db: Session = Depends(get_db)):
    """Master-patient-index style lookup: exact name + birth year + sex at another hospital. No browsing,
    no partial matches; ambiguous results are refused so the requester must ask for the pseudonym."""
    _check_birth_year(birth_year)
    hits = (db.query(Patient).join(Hospital, Patient.hospital_id == Hospital.id)
            .filter(Patient.hospital_id != user.hospital_id, Hospital.active.is_(True), Patient.birth_year == birth_year, Patient.sex == sex,
                    func.lower(Patient.display_name) == " ".join(name.split()).lower())
            .limit(2).all())
    audit.log(db, "patient.match_lookup", user=user, resource=f"matches:{len(hits)}")
    if not hits:
        raise HTTPException(404, "no exact match at another hospital")
    if len(hits) > 1:
        raise HTTPException(409, "more than one patient matches; ask the patient for their ID")
    p = hits[0]
    return {"pseudo_id": p.pseudo_id, "hospital_id": p.hospital_id, "hospital_name": p.hospital.name}


@router.get("/patients/{pid}")
def get_patient(pid: int, user: User = Depends(require(Perm.patient_read)), db: Session = Depends(get_db)):
    p = db.get(Patient, pid)
    if p is None:
        raise HTTPException(404, "patient not found")
    _own(user, p)
    bundle = _record(p)
    audit.log(db, "patient.read", user=user, resource=f"patient:{p.pseudo_id}")
    return {**patient_summary(p), "features": features_from_bundle(bundle), "fhir": bundle}


def _check_birth_year(year: int):
    if year > _now().year:
        raise HTTPException(422, "birth year cannot be in the future")


class PatientIn(BaseModel):
    local_id: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=2, max_length=120)
    sex: str = Field(pattern="^(male|female)$")
    birth_year: int = Field(ge=1900)
    features: dict[str, float | None] = {}
    diagnosis: int | None = Field(default=None, ge=0, le=1)  # confirmed CAD 1 / ruled out 0; used for training


@router.post("/patients", status_code=201)
def create_patient(body: PatientIn, user: User = Depends(require(Perm.patient_write)), db: Session = Depends(get_db)):
    allowed = {"trestbps", "chol", "thalach", "oldpeak", "fbs", "exang", "cp", "restecg"}
    if set(body.features) - allowed:
        raise HTTPException(422, f"unknown features: {sorted(set(body.features) - allowed)}")
    _check_birth_year(body.birth_year)
    h = db.get(Hospital, user.hospital_id)
    if db.query(Patient).filter_by(pseudo_id=pseudonymize(h.code, body.local_id)).first():
        raise HTTPException(409, "patient exists")
    p = create_patient_record(db, h, body.local_id, body.display_name, body.sex, body.birth_year,
                              {k: v for k, v in body.features.items() if v is not None}, body.diagnosis)
    db.commit()
    datasets.refresh_node(db, h)
    audit.log(db, "patient.create", user=user, resource=f"patient:{p.pseudo_id}")
    return patient_summary(p)


# ------------------------------------------------------------------ consent
class ConsentIn(BaseModel):
    purpose: str = Field(pattern="^(treatment|care_coordination|research)$")
    granted_to_hospital_id: int | None = None
    valid_days: int = Field(default=180, ge=1, le=3650)


def consent_out(c: Consent, db: Session) -> dict:
    p = db.get(Patient, c.patient_id)
    h = db.get(Hospital, c.granted_to_hospital_id) if c.granted_to_hospital_id else None
    active = c.revoked_at is None and _aware(c.valid_until) > _now()
    return {"id": c.id, "patient_id": c.patient_id, "purpose": c.purpose, "scope": c.scope,
            "granted_to_hospital_id": c.granted_to_hospital_id, "granted_to": h.name if h else "any participating hospital",
            "valid_until": _aware(c.valid_until).isoformat(), "revoked_at": c.revoked_at and _aware(c.revoked_at).isoformat(),
            "active": active, "created_at": _aware(c.created_at).isoformat(),
            "fhir": consent_resource(c.id, p.pseudo_id, c.purpose, h.name if h else None, _aware(c.valid_until),
                                     c.revoked_at is not None)}


@router.get("/patients/{pid}/consents")
def list_consents(pid: int, user: User = Depends(require(Perm.consent_manage)), db: Session = Depends(get_db)):
    p = db.get(Patient, pid)
    if p is None:
        raise HTTPException(404, "patient not found")
    _own(user, p)
    return [consent_out(c, db) for c in db.query(Consent).filter_by(patient_id=pid).order_by(Consent.id.desc())]


@router.post("/patients/{pid}/consents", status_code=201)
def record_consent(pid: int, body: ConsentIn, user: User = Depends(require(Perm.consent_manage)), db: Session = Depends(get_db)):
    p = db.get(Patient, pid)
    if p is None:
        raise HTTPException(404, "patient not found")
    _own(user, p)
    c = Consent(patient_id=pid, purpose=body.purpose, granted_to_hospital_id=body.granted_to_hospital_id,
                valid_until=_now() + timedelta(days=body.valid_days), recorded_by=user.id)
    db.add(c)
    db.commit()
    audit.log(db, "consent.record", user=user, resource=f"patient:{p.pseudo_id}",
              detail={"consent_id": c.id, "purpose": c.purpose, "to": body.granted_to_hospital_id})
    if c.purpose == "research":
        datasets.refresh_node(db, p.hospital)  # research consent makes a diagnosed patient a training row
    return consent_out(c, db)


@router.post("/consents/{cid}/revoke")
def revoke_consent(cid: int, user: User = Depends(require(Perm.consent_manage)), db: Session = Depends(get_db)):
    c = db.get(Consent, cid)
    if c is None:
        raise HTTPException(404, "consent not found")
    p = db.get(Patient, c.patient_id)
    _own(user, p)
    if c.revoked_at is None:
        c.revoked_at = _now()
        # revocation cascades to every share that relied on this consent: keys are destroyed
        for s in db.query(ShareRequest).filter_by(consent_id=c.id, status=ShareStatus.approved):
            s.status, s.recipient_wrapped_dek = ShareStatus.revoked, None
        db.commit()
        audit.log(db, "consent.revoke", user=user, resource=f"patient:{p.pseudo_id}", detail={"consent_id": c.id})
        if c.purpose == "research":
            datasets.refresh_node(db, p.hospital)
    return consent_out(c, db)


# ------------------------------------------------------------------ sharing
class ShareIn(BaseModel):
    pseudo_id: str = Field(min_length=6, max_length=40)
    purpose: str = Field(pattern="^(treatment|care_coordination|research)$")
    justification: str = Field(min_length=5, max_length=1000)


class DecisionIn(BaseModel):
    approve: bool
    valid_days: int = Field(default=30, ge=1, le=365)
    note: str = Field(default="", max_length=500)


def _matching_consent(db: Session, s: ShareRequest) -> Consent | None:
    for c in db.query(Consent).filter_by(patient_id=s.patient_id, purpose=s.purpose):
        if c.revoked_at is None and _aware(c.valid_until) > _now() and \
                c.granted_to_hospital_id in (None, s.requesting_hospital_id):
            return c
    return None


def _expire(s: ShareRequest):
    if s.status == ShareStatus.approved and s.expires_at and _aware(s.expires_at) < _now():
        s.status, s.recipient_wrapped_dek = ShareStatus.expired, None


def share_out(s: ShareRequest, db: Session) -> dict:
    _expire(s)
    req_h, own_h = db.get(Hospital, s.requesting_hospital_id), db.get(Hospital, s.owner_hospital_id)
    requester, decider = db.get(User, s.requested_by), db.get(User, s.decided_by) if s.decided_by else None
    return {"id": s.id, "pseudo_id": s.patient.pseudo_id, "purpose": s.purpose, "justification": s.justification,
            "status": s.status.value, "owner_hospital": own_h.name, "owner_hospital_id": own_h.id,
            "requesting_hospital": req_h.name, "requesting_hospital_id": req_h.id,
            "requested_by": requester.full_name, "decided_by": decider.full_name if decider else None,
            "created_at": _aware(s.created_at).isoformat(),
            "decided_at": s.decided_at and _aware(s.decided_at).isoformat(),
            "expires_at": s.expires_at and _aware(s.expires_at).isoformat(), "consent_id": s.consent_id,
            "consent_on_file": _matching_consent(db, s) is not None}


@router.post("/shares", status_code=201)
def request_share(body: ShareIn, user: User = Depends(require(Perm.share_request)), db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.pseudo_id == body.pseudo_id.strip().upper()).first()
    if p is None or p.hospital_id == user.hospital_id or not p.hospital.active:
        raise HTTPException(404, "no external record with that pseudonym")
    s = ShareRequest(patient_id=p.id, owner_hospital_id=p.hospital_id, requesting_hospital_id=user.hospital_id,
                     requested_by=user.id, purpose=body.purpose, justification=body.justification)
    db.add(s)
    db.commit()
    audit.log(db, "share.request", user=user, resource=f"share:{s.id}", detail={"patient": p.pseudo_id, "purpose": s.purpose})
    return share_out(s, db)


def share_actor(user: User = Depends(current_user)) -> User:
    """Clinicians (requesters) and hospital admins (deciders) can both list their tenant's shares."""
    if not (has_perm(user, Perm.share_view) or has_perm(user, Perm.share_decide)):
        raise HTTPException(403, "missing permission share:view or share:decide")
    return user


@router.get("/shares")
def list_shares(direction: str = Query("all", pattern="^(incoming|outgoing|all)$"),
                 user: User = Depends(share_actor), db: Session = Depends(get_db)):
    q = db.query(ShareRequest)
    if direction == "incoming":
        q = q.filter(ShareRequest.owner_hospital_id == user.hospital_id)
    elif direction == "outgoing":
        q = q.filter(ShareRequest.requesting_hospital_id == user.hospital_id)
    else:
        q = q.filter(or_(ShareRequest.owner_hospital_id == user.hospital_id,
                         ShareRequest.requesting_hospital_id == user.hospital_id))
    out = [share_out(s, db) for s in q.order_by(ShareRequest.id.desc())]
    db.commit()
    return out


@router.post("/shares/{sid}/decide")
def decide(sid: int, body: DecisionIn, user: User = Depends(require(Perm.share_decide)), db: Session = Depends(get_db)):
    s = db.get(ShareRequest, sid)
    if s is None or s.owner_hospital_id != user.hospital_id:
        raise HTTPException(404, "share request not found")
    if s.status != ShareStatus.pending:
        raise HTTPException(409, f"request is already {s.status.value}")
    if body.approve:
        c = _matching_consent(db, s)
        if c is None:
            raise HTTPException(409, "no active patient consent covers this purpose and recipient")
        p = s.patient
        req_h = db.get(Hospital, s.requesting_hospital_id)
        s.recipient_wrapped_dek = rewrap(p.hospital.code, req_h.code, p.wrapped_dek)
        s.status, s.consent_id = ShareStatus.approved, c.id
        s.expires_at = min(_now() + timedelta(days=body.valid_days), _aware(c.valid_until))
    else:
        s.status = ShareStatus.denied
    s.decided_by, s.decided_at = user.id, _now()
    db.commit()
    audit.log(db, "share.approve" if body.approve else "share.deny", user=user, resource=f"share:{s.id}",
              detail={"note": body.note})
    return share_out(s, db)


@router.post("/shares/{sid}/revoke")
def revoke_share(sid: int, user: User = Depends(require(Perm.share_decide)), db: Session = Depends(get_db)):
    s = db.get(ShareRequest, sid)
    if s is None or s.owner_hospital_id != user.hospital_id:
        raise HTTPException(404, "share request not found")
    if s.status == ShareStatus.approved:
        s.status, s.recipient_wrapped_dek = ShareStatus.revoked, None
        db.commit()
        audit.log(db, "share.revoke", user=user, resource=f"share:{s.id}")
    return share_out(s, db)


@router.get("/shares/{sid}/record")
def view_shared(sid: int, user: User = Depends(require(Perm.share_view)), db: Session = Depends(get_db)):
    s = db.get(ShareRequest, sid)
    if s is None or s.requesting_hospital_id != user.hospital_id:
        raise HTTPException(404, "share not found")
    _expire(s)
    if s.status != ShareStatus.approved or s.recipient_wrapped_dek is None:
        db.commit()
        audit.log(db, "share.view", user=user, resource=f"share:{s.id}", outcome="denied")
        raise HTTPException(403, f"share is {s.status.value}")
    c = db.get(Consent, s.consent_id)
    if c is None or c.revoked_at is not None:
        raise HTTPException(403, "consent revoked")
    req_h = db.get(Hospital, s.requesting_hospital_id)
    bundle = _record(s.patient, wrapped=s.recipient_wrapped_dek, tenant=req_h.code)
    # purpose limitation: only the resource types in the consent scope are released
    allowed = set(c.scope.split(",")) | {"Patient"}
    bundle["entry"] = [e for e in bundle["entry"] if e["resource"]["resourceType"] in allowed]
    audit.log(db, "share.view", user=user, resource=f"share:{s.id}", detail={"patient": s.patient.pseudo_id})
    return {"share": share_out(s, db), "fhir": bundle, "features": features_from_bundle(bundle)}


__all__ = ["router", "create_patient_record"]
