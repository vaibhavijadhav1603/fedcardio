"""Passwords, JWTs (with refresh rotation + reuse detection), TOTP MFA and RBAC."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
import pyotp
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import RefreshToken, Role, User

# ---------------------------------------------------------------- passwords (scrypt, stdlib)
_N, _R, _P = 2**14, 8, 1


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        dk = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(h))
    except ValueError:
        return False


# ---------------------------------------------------------------- RBAC (deny by default)
class Perm(str, Enum):
    patient_read = "patient:read"
    patient_write = "patient:write"
    share_request = "share:request"
    share_decide = "share:decide"
    share_view = "share:view"
    consent_manage = "consent:manage"
    predict = "predict"
    fl_view = "fl:view"
    fl_run = "fl:run"
    results_view = "results:view"
    model_view = "model:view"
    model_promote = "model:promote"
    audit_view = "audit:view"
    audit_export = "audit:export"
    user_manage = "user:manage"
    hospital_manage = "hospital:manage"
    dataset_manage = "dataset:manage"


ROLE_PERMS: dict[Role, set[Perm]] = {
    Role.platform_admin: {Perm.fl_view, Perm.results_view, Perm.model_view, Perm.model_promote,
                          Perm.audit_view, Perm.user_manage, Perm.hospital_manage},
    Role.hospital_admin: {Perm.share_decide, Perm.consent_manage, Perm.fl_view, Perm.results_view,
                          Perm.model_view, Perm.audit_view, Perm.user_manage, Perm.patient_read,
                          Perm.dataset_manage},
    Role.clinician: {Perm.patient_read, Perm.patient_write, Perm.share_request, Perm.share_view,
                     Perm.consent_manage, Perm.predict, Perm.model_view, Perm.results_view},
    Role.data_scientist: {Perm.fl_view, Perm.fl_run, Perm.results_view, Perm.model_view},
    Role.auditor: {Perm.audit_view, Perm.audit_export, Perm.results_view, Perm.model_view, Perm.fl_view},
}
# platform_admin deliberately has NO patient-data permissions (least privilege).


def has_perm(user: User, perm: Perm) -> bool:
    return perm in ROLE_PERMS.get(user.role, set())


# ---------------------------------------------------------------- tokens
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user: User, mfa: bool) -> str:
    s = get_settings()
    payload = {"sub": str(user.id), "role": user.role.value, "hid": user.hospital_id, "mfa": mfa,
               "iss": s.jwt_issuer, "iat": _now(), "exp": _now() + timedelta(minutes=s.access_ttl_minutes),
               "typ": "access", "jti": uuid.uuid4().hex}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def create_mfa_challenge(user: User) -> str:
    s = get_settings()
    return jwt.encode({"sub": str(user.id), "typ": "mfa", "iss": s.jwt_issuer,
                       "exp": _now() + timedelta(minutes=5)}, s.jwt_secret, algorithm="HS256")


def decode(token: str, typ: str) -> dict:
    s = get_settings()
    try:
        data = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], issuer=s.jwt_issuer)
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from e
    if data.get("typ") != typ:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong token type")
    return data


def issue_refresh(db: Session, user: User, family: str | None = None) -> str:
    s = get_settings()
    rt = RefreshToken(jti=secrets.token_urlsafe(32), family=family or uuid.uuid4().hex, user_id=user.id,
                      expires_at=_now() + timedelta(hours=s.refresh_ttl_hours))
    db.add(rt)
    db.commit()
    return rt.jti


def can_sign_in(user: User | None) -> bool:
    """Disabled accounts, and every account of a deactivated hospital, are locked out."""
    return user is not None and user.active and (user.hospital is None or user.hospital.active)


def rotate_refresh(db: Session, token: str) -> tuple[User, str]:
    """Single-use refresh tokens. Reusing a rotated token revokes the whole family (theft detection)."""
    rt = db.get(RefreshToken, token)
    if rt is None:
        raise HTTPException(401, "invalid refresh token")
    if rt.revoked:
        for t in db.query(RefreshToken).filter_by(family=rt.family):
            t.revoked = True
        db.commit()
        raise HTTPException(401, "refresh token reuse detected; session revoked")
    exp = rt.expires_at if rt.expires_at.tzinfo else rt.expires_at.replace(tzinfo=timezone.utc)
    if exp < _now():
        raise HTTPException(401, "refresh token expired")
    rt.revoked = True
    user = db.get(User, rt.user_id)
    db.commit()
    if not can_sign_in(user):
        raise HTTPException(401, "account disabled")
    return user, issue_refresh(db, user, rt.family)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


# ---------------------------------------------------------------- dependencies
bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(401, "not authenticated", headers={"WWW-Authenticate": "Bearer"})
    data = decode(creds.credentials, "access")
    user = db.get(User, int(data["sub"]))
    if not can_sign_in(user):
        raise HTTPException(401, "account disabled")
    if user.role.value in get_settings().require_mfa_roles and not data.get("mfa"):
        raise HTTPException(403, "MFA required for this role")
    request.state.user = user
    return user


def require(perm: Perm):
    def dep(user: User = Depends(current_user)) -> User:
        if not has_perm(user, perm):
            raise HTTPException(403, f"missing permission {perm.value}")
        return user
    return dep
