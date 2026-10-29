"""Hospitals and users. Hospital admins manage only their own tenant; nobody can grant platform_admin
except a platform_admin."""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import audit, datasets
from ..crypto import get_kms
from ..db import get_db
from ..models import (
    Consent,
    FLNode,
    Hospital,
    HospitalDataset,
    Patient,
    RefreshToken,
    Role,
    ShareRequest,
    ShareStatus,
    TrainingJob,
    User,
)
from ..security import Perm, current_user, has_perm, hash_password, require
from .auth import user_out

router = APIRouter(tags=["admin"])


def hospital_out(h: Hospital, db: Session, detail: bool = False) -> dict:
    out = {"id": h.id, "code": h.code, "name": h.name, "city": h.city, "active": h.active}
    if detail:  # counts only: the platform admin never sees patient data itself
        out |= {"decommissioned_at": datasets.iso_utc(h.decommissioned_at),
                "n_users": db.query(User).filter_by(hospital_id=h.id).count(),
                "n_patients": db.query(Patient).filter_by(hospital_id=h.id).count(),
                "dataset": datasets.summary(db.query(HospitalDataset).filter_by(hospital_id=h.id).first()),
                "n_training": node.n_records if (node := db.query(FLNode).filter_by(hospital_id=h.id).first()) else 0}
    return out


@router.get("/hospitals")
def hospitals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    manage = has_perm(user, Perm.hospital_manage)
    q = db.query(Hospital).order_by(Hospital.id)
    if not manage:
        q = q.filter(Hospital.active.is_(True))
    return [hospital_out(h, db, detail=manage) for h in q]


class AdminIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=5, max_length=200)  # optional: the launcher needs none


class HospitalIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=200)
    city: str = Field(default="", max_length=100)
    admin: AdminIn | None = None  # the hospital's first hospital admin, created in the same transaction


@router.post("/hospitals", status_code=201)
def create_hospital(body: HospitalIn, user: User = Depends(require(Perm.hospital_manage)), db: Session = Depends(get_db)):
    if db.query(Hospital).filter_by(code=body.code).first():
        raise HTTPException(409, "hospital code exists")
    if body.admin and db.query(User).filter_by(email=body.admin.email.lower()).first():
        raise HTTPException(409, "admin email exists")
    h = Hospital(code=body.code, name=body.name, city=body.city)
    db.add(h)
    db.flush()
    admin = None
    if body.admin:
        admin = User(email=body.admin.email.lower(), full_name=body.admin.full_name, role=Role.hospital_admin,
                     hospital_id=h.id, password_hash=hash_password(body.admin.password or secrets.token_urlsafe(24)))
        db.add(admin)
    db.commit()
    audit.log(db, "hospital.create", user=user, resource=f"hospital:{h.id}")
    if admin:
        audit.log(db, "user.create", user=user, resource=f"user:{admin.id}", detail={"role": admin.role.value})
    return hospital_out(h, db, detail=True)


def _hospital(hid: int, db: Session) -> Hospital:
    h = db.get(Hospital, hid)
    if h is None:
        raise HTTPException(404, "hospital not found")
    return h


@router.post("/hospitals/{hid}/deactivate")
def deactivate_hospital(hid: int, user: User = Depends(require(Perm.hospital_manage)), db: Session = Depends(get_db)):
    """Take a hospital off the platform but keep its records: sign-ins blocked, FL node offline,
    open shares and consents naming it closed (their keys destroyed). Reversible, except the shares."""
    h = _hospital(hid, db)
    if not h.active:
        raise HTTPException(409, "hospital is already deactivated")
    now = datetime.now(timezone.utc)
    h.active, h.decommissioned_at = False, now
    shares = db.query(ShareRequest).filter(
        or_(ShareRequest.owner_hospital_id == h.id, ShareRequest.requesting_hospital_id == h.id),
        ShareRequest.status.in_([ShareStatus.pending, ShareStatus.approved])).all()
    for sh in shares:
        sh.status = ShareStatus.denied if sh.status == ShareStatus.pending else ShareStatus.revoked
        sh.recipient_wrapped_dek = None
    consents = db.query(Consent).filter(Consent.granted_to_hospital_id == h.id, Consent.revoked_at.is_(None)).all()
    for c in consents:
        c.revoked_at = now
    user_ids = [u.id for u in db.query(User).filter_by(hospital_id=h.id)]
    db.query(RefreshToken).filter(RefreshToken.user_id.in_(user_ids)).update({"revoked": True}, synchronize_session=False)
    for n in db.query(FLNode).filter_by(hospital_id=h.id):
        n.status = "offline"
    db.commit()
    audit.log(db, "hospital.deactivate", user=user, resource=f"hospital:{h.id}",
              detail={"shares_closed": len(shares), "consents_revoked": len(consents), "users_locked": len(user_ids)})
    return hospital_out(h, db, detail=True)


@router.post("/hospitals/{hid}/reactivate")
def reactivate_hospital(hid: int, user: User = Depends(require(Perm.hospital_manage)), db: Session = Depends(get_db)):
    h = _hospital(hid, db)
    if h.active:
        raise HTTPException(409, "hospital is already active")
    h.active, h.decommissioned_at = True, None
    db.commit()
    datasets.refresh_node(db, h)
    audit.log(db, "hospital.reactivate", user=user, resource=f"hospital:{h.id}")
    return hospital_out(h, db, detail=True)


@router.delete("/hospitals/{hid}")
def delete_hospital(hid: int, confirm: str = Query(..., description="must equal the hospital's tenant code"),
                    user: User = Depends(require(Perm.hospital_manage)), db: Session = Depends(get_db)):
    """Permanently erase a deactivated hospital: patients, consents, shares, dataset, FL node and
    accounts, then destroy its KEK so any leftover ciphertext is unreadable. The audit log is kept
    (it is hash-chained, and it records the deletion)."""
    h = _hospital(hid, db)
    if h.active:
        raise HTTPException(409, "deactivate the hospital before deleting it")
    if confirm != h.code:
        raise HTTPException(400, "confirmation does not match the hospital's tenant code")
    pids = [p.id for p in db.query(Patient).filter_by(hospital_id=h.id)]
    n_shares = db.query(ShareRequest).filter(or_(
        ShareRequest.patient_id.in_(pids), ShareRequest.owner_hospital_id == h.id,
        ShareRequest.requesting_hospital_id == h.id)).delete(synchronize_session=False)
    n_consents = db.query(Consent).filter(or_(
        Consent.patient_id.in_(pids), Consent.granted_to_hospital_id == h.id)).delete(synchronize_session=False)
    n_patients = db.query(Patient).filter_by(hospital_id=h.id).delete(synchronize_session=False)
    db.query(HospitalDataset).filter_by(hospital_id=h.id).delete(synchronize_session=False)
    db.query(FLNode).filter_by(hospital_id=h.id).delete(synchronize_session=False)
    deleted, kept = 0, 0
    for u in db.query(User).filter_by(hospital_id=h.id).all():
        db.query(RefreshToken).filter_by(user_id=u.id).delete(synchronize_session=False)
        if u.role not in HOSPITAL_ROLES:
            u.hospital_id = None  # platform-level roles outlive any hospital
            kept += 1
        elif db.query(TrainingJob).filter_by(created_by=u.id).first():
            u.hospital_id, u.active = None, False  # keep the author of past training jobs, detached and disabled
            kept += 1
        else:
            db.delete(u)
            deleted += 1
    code = h.code
    db.delete(h)
    db.commit()
    get_kms().destroy(code)
    audit.log(db, "hospital.delete", user=user, resource=f"hospital:{hid}",
              detail={"code": code, "patients": n_patients, "consents": n_consents, "shares": n_shares,
                      "users_deleted": deleted, "users_detached": kept})
    return {"deleted": hid}


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    role: Role
    hospital_id: int | None = None
    password: str | None = Field(default=None, min_length=5, max_length=200)  # optional: the launcher needs none


class UserPatch(BaseModel):
    role: Role | None = None
    active: bool | None = None


# Who may hand out which role. There is a single platform admin and nobody can create another; the platform
# admin appoints each hospital's admins, and each hospital admin appoints that hospital's clinicians.
ASSIGNABLE: dict[Role, set[Role]] = {
    Role.platform_admin: {Role.hospital_admin, Role.data_scientist, Role.auditor},
    Role.hospital_admin: {Role.hospital_admin, Role.clinician},
}
HOSPITAL_ROLES = {Role.hospital_admin, Role.clinician}  # the others are platform-level and belong to no hospital


def _check_role(actor: User, role: Role, hospital_id: int | None):
    if role not in ASSIGNABLE.get(actor.role, set()):
        who = "the platform admin" if role == Role.hospital_admin else "a hospital admin"
        raise HTTPException(403, "there is only one platform admin" if role == Role.platform_admin
                            else f"only {who} can create or assign the {role.value} role")
    if (role in HOSPITAL_ROLES) != (hospital_id is not None):
        raise HTTPException(422, f"a {role.value} must {'' if role in HOSPITAL_ROLES else 'not '}belong to a hospital")


def _scope(actor: User, target_hospital: int | None):
    if actor.role == Role.platform_admin:
        return
    if actor.role == Role.hospital_admin and target_hospital == actor.hospital_id:
        return
    raise HTTPException(403, "outside your tenant")


@router.get("/users")
def list_users(actor: User = Depends(require(Perm.user_manage)), db: Session = Depends(get_db)):
    q = db.query(User).order_by(User.id)
    if actor.role != Role.platform_admin:
        q = q.filter(User.hospital_id == actor.hospital_id)
    return [{**user_out(u), "active": u.active, "created_at": u.created_at.isoformat()} for u in q]


@router.post("/users", status_code=201)
def create_user(body: UserIn, actor: User = Depends(require(Perm.user_manage)), db: Session = Depends(get_db)):
    _scope(actor, body.hospital_id)
    if body.hospital_id is not None:
        h = db.get(Hospital, body.hospital_id)
        if h is None or not h.active:
            raise HTTPException(409, "hospital not found or deactivated")
    _check_role(actor, body.role, body.hospital_id)
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(409, "email exists")
    u = User(email=body.email.lower(), full_name=body.full_name, role=body.role, hospital_id=body.hospital_id,
             password_hash=hash_password(body.password or secrets.token_urlsafe(24)))
    db.add(u)
    db.commit()
    audit.log(db, "user.create", user=actor, resource=f"user:{u.id}", detail={"role": body.role.value})
    return user_out(u)


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, actor: User = Depends(require(Perm.user_manage)), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "not found")
    _scope(actor, u.hospital_id)
    if u.id == actor.id:
        raise HTTPException(400, "cannot modify your own account here")
    if body.role is not None and body.role != u.role:
        _check_role(actor, body.role, u.hospital_id)
    before = {"role": u.role.value, "active": u.active}
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    db.commit()
    audit.log(db, "user.update", user=actor, resource=f"user:{u.id}",
              detail={"before": before, "after": {"role": u.role.value, "active": u.active}})
    return user_out(u)


class ResetIn(BaseModel):
    password: str = Field(min_length=5, max_length=200)


@router.post("/users/{uid}/password")
def reset_password(uid: int, body: ResetIn, actor: User = Depends(require(Perm.user_manage)), db: Session = Depends(get_db)):
    """Give a user a new password and end their sessions.
    You may only reset accounts whose role you could appoint, so the platform admin can never take over a
    clinician's account and reach patient data that way."""
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "not found")
    _scope(actor, u.hospital_id)
    if u.id == actor.id:
        raise HTTPException(400, "change your own password from your account menu")
    if u.role not in ASSIGNABLE.get(actor.role, set()):
        raise HTTPException(403, f"you cannot reset a {u.role.value}'s password")
    u.password_hash = hash_password(body.password)
    db.query(RefreshToken).filter_by(user_id=u.id).update({"revoked": True}, synchronize_session=False)
    db.commit()
    audit.log(db, "user.password_reset", user=actor, resource=f"user:{u.id}")
    return user_out(u)
