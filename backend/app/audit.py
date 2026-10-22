"""Append-only, hash-chained audit log. Each event's hash covers its content and the previous hash,
so editing or deleting any past event breaks verification from that point on."""
from __future__ import annotations

import hashlib
import json
from datetime import timezone

from sqlalchemy.orm import Session

from .models import AuditEvent, User, utcnow

GENESIS = "0" * 64


def _digest(ev: AuditEvent) -> str:
    ts = ev.ts if ev.ts.tzinfo else ev.ts.replace(tzinfo=timezone.utc)
    body = json.dumps({
        "seq": ev.seq, "ts": ts.isoformat(), "actor_id": ev.actor_id, "actor_email": ev.actor_email,
        "actor_role": ev.actor_role, "hospital_id": ev.hospital_id, "action": ev.action,
        "resource": ev.resource, "outcome": ev.outcome, "detail": ev.detail, "prev": ev.prev_hash,
    }, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def log(db: Session, action: str, *, user: User | None = None, resource: str = "", outcome: str = "success",
        detail: dict | None = None, commit: bool = True) -> AuditEvent:
    last = db.query(AuditEvent).order_by(AuditEvent.seq.desc()).first()
    ev = AuditEvent(
        seq=(last.seq + 1) if last else 1, ts=utcnow(),
        actor_id=user.id if user else None, actor_email=user.email if user else "system",
        actor_role=user.role.value if user else "system", hospital_id=user.hospital_id if user else None,
        action=action, resource=resource, outcome=outcome, detail=detail or {},
        prev_hash=last.hash if last else GENESIS, hash="",
    )
    ev.hash = _digest(ev)
    db.add(ev)
    if commit:
        db.commit()
    return ev


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    n = 0
    for ev in db.query(AuditEvent).order_by(AuditEvent.seq):
        n += 1
        if ev.prev_hash != prev or _digest(ev) != ev.hash:
            return {"valid": False, "events_checked": n, "first_bad_seq": ev.seq}
        prev = ev.hash
    return {"valid": True, "events_checked": n, "head": prev}
