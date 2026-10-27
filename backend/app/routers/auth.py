from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import RefreshToken, User
from ..security import (
    can_sign_in,
    create_access_token,
    create_mfa_challenge,
    current_user,
    decode,
    hash_password,
    issue_refresh,
    new_totp_secret,
    rotate_refresh,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "fc_refresh"


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class MfaIn(BaseModel):
    challenge: str
    code: str = Field(pattern=r"^\d{6}$")


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def user_out(u: User) -> dict:
    from ..security import ROLE_PERMS
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role.value,
            "hospital_id": u.hospital_id, "hospital_name": u.hospital.name if u.hospital else None,
            "hospital_code": u.hospital.code if u.hospital else None, "mfa_enabled": u.mfa_enabled,
            "must_change_password": u.must_change_password,
            "permissions": sorted(p.value for p in ROLE_PERMS.get(u.role, set()))}


def _session(resp: Response, db: Session, user: User, mfa: bool, family: str | None = None) -> dict:
    refresh = issue_refresh(db, user, family)
    s = get_settings()
    resp.set_cookie(COOKIE, refresh, httponly=True, secure=s.env != "dev", samesite="strict",
                    max_age=s.refresh_ttl_hours * 3600, path=s.cookie_path)
    return {"access_token": create_access_token(user, mfa), "token_type": "bearer",
            "expires_in": s.access_ttl_minutes * 60, "user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, resp: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email.lower()).first()
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        audit.log(db, "auth.login", resource=body.email.lower(), outcome="failure")
        raise HTTPException(401, "invalid email or password")
    if not can_sign_in(user):
        audit.log(db, "auth.login", user=user, outcome="failure", detail={"reason": "hospital deactivated"})
        raise HTTPException(403, "your hospital has been deactivated on this platform")
    if user.mfa_enabled:
        return {"mfa_required": True, "challenge": create_mfa_challenge(user)}
    audit.log(db, "auth.login", user=user)
    return _session(resp, db, user, mfa=False)


@router.post("/mfa/verify")
def mfa_verify(body: MfaIn, resp: Response, db: Session = Depends(get_db)):
    data = decode(body.challenge, "mfa")
    user = db.get(User, int(data["sub"]))
    if not can_sign_in(user) or not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        audit.log(db, "auth.mfa", user=user, outcome="failure")
        raise HTTPException(401, "invalid code")
    audit.log(db, "auth.login", user=user, detail={"mfa": True})
    return _session(resp, db, user, mfa=True)


@router.post("/refresh")
def refresh(request: Request, resp: Response, db: Session = Depends(get_db)):
    # CSRF mitigation: SameSite=strict cookie + a custom header a cross-site form cannot set.
    if request.headers.get("x-requested-with") != "fedcardio":
        raise HTTPException(403, "missing CSRF header")
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "no session")
    user, new_refresh = rotate_refresh(db, token)
    s = get_settings()
    resp.set_cookie(COOKIE, new_refresh, httponly=True, secure=s.env != "dev", samesite="strict",
                    max_age=s.refresh_ttl_hours * 3600, path=s.cookie_path)
    return {"access_token": create_access_token(user, user.mfa_enabled), "token_type": "bearer",
            "expires_in": s.access_ttl_minutes * 60, "user": user_out(user)}


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/password")
def change_password(body: PasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Change your own password. Every other signed-in session of this account is ended."""
    if not verify_password(body.current_password, user.password_hash):
        audit.log(db, "auth.password_change", user=user, outcome="failure")
        raise HTTPException(400, "current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(400, "choose a password different from the current one")
    user.password_hash, user.must_change_password = hash_password(body.new_password), False
    rt = db.get(RefreshToken, request.cookies.get(COOKIE) or "")
    keep = rt.family if rt and rt.user_id == user.id else None
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id, RefreshToken.family != keep).update(
        {"revoked": True}, synchronize_session=False)
    db.commit()
    audit.log(db, "auth.password_change", user=user)
    return user_out(user)


@router.post("/logout")
def logout(request: Request, resp: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if token and (rt := db.get(RefreshToken, token)):
        for t in db.query(RefreshToken).filter_by(family=rt.family):
            t.revoked = True
        db.commit()
    resp.delete_cookie(COOKIE, path=get_settings().cookie_path)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/mfa/setup")
def mfa_setup(user: User = Depends(current_user), db: Session = Depends(get_db)):
    import pyotp
    user.totp_secret = new_totp_secret()
    db.commit()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name="FedCardio")
    return {"secret": user.totp_secret, "otpauth_uri": uri}


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        raise HTTPException(400, "invalid code")
    user.mfa_enabled = True
    db.commit()
    audit.log(db, "auth.mfa_enabled", user=user)
    return {"mfa_enabled": True}


DEMO_DOMAIN = "@fedcardio.dev"


class DemoIn(BaseModel):
    password: str = Field(max_length=200)


@router.post("/demo-accounts")
def demo_accounts(body: DemoIn, db: Session = Depends(get_db)):
    """Dev only: the demo accounts that currently exist, for the login page. One admin and one clinician
    per active hospital, then the platform-level accounts. Hidden unless the demo password is given, and
    disabled in any non-dev environment."""
    import hmac
    s = get_settings()
    if s.env != "dev" or not hmac.compare_digest(body.password.encode(), s.demo_password.encode()):
        raise HTTPException(404, "not found")
    from ..models import Hospital, Role
    users = [u for u in db.query(User).filter(User.email.like(f"%{DEMO_DOMAIN}"), User.active.is_(True))
             .order_by(User.id) if can_sign_in(u)]
    out = [u for u in users if u.role == Role.platform_admin]
    for h in db.query(Hospital).filter(Hospital.active.is_(True)).order_by(Hospital.id):
        for role in (Role.hospital_admin, Role.clinician):
            out += [u for u in users if u.hospital_id == h.id and u.role == role][:1]
    out += [u for u in users if u.role in (Role.data_scientist, Role.auditor)]
    return [{"email": u.email, "role": u.role.value, "hospital": u.hospital.name if u.hospital else None} for u in out]
