"""Hospitals and users. Hospital admins manage only their own tenant; nobody can grant platform_admin
except a platform_admin."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Hospital, Role, User
from ..security import Perm, current_user, hash_password, require
from .auth import user_out

router = APIRouter(tags=["admin"])


@router.get("/hospitals")
def hospitals(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": h.id, "code": h.code, "name": h.name, "city": h.city} for h in db.query(Hospital).order_by(Hospital.id)]


class HospitalIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=200)
    city: str = Field(default="", max_length=100)


@router.post("/hospitals", status_code=201)
def create_hospital(body: HospitalIn, user: User = Depends(require(Perm.hospital_manage)), db: Session = Depends(get_db)):
    if db.query(Hospital).filter_by(code=body.code).first():
        raise HTTPException(409, "hospital code exists")
    h = Hospital(**body.model_dump())
    db.add(h)
    db.commit()
    audit.log(db, "hospital.create", user=user, resource=f"hospital:{h.id}")
    return {"id": h.id, "code": h.code, "name": h.name, "city": h.city}


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    role: Role
    hospital_id: int | None = None
    password: str = Field(min_length=10, max_length=200)


class UserPatch(BaseModel):
    role: Role | None = None
    active: bool | None = None


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
    if body.role == Role.platform_admin and actor.role != Role.platform_admin:
        raise HTTPException(403, "cannot grant platform_admin")
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(409, "email exists")
    u = User(email=body.email.lower(), full_name=body.full_name, role=body.role, hospital_id=body.hospital_id,
             password_hash=hash_password(body.password))
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
    if body.role == Role.platform_admin and actor.role != Role.platform_admin:
        raise HTTPException(403, "cannot grant platform_admin")
    before = {"role": u.role.value, "active": u.active}
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    db.commit()
    audit.log(db, "user.update", user=actor, resource=f"user:{u.id}",
              detail={"before": before, "after": {"role": u.role.value, "active": u.active}})
    return user_out(u)
