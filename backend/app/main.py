"""FedCardio API: research demonstrator. Not for clinical use."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import Base, add_missing_sqlite_columns, engine
from .routers import admin, auth, datasets, fl, ml, patients

settings = get_settings()
app = FastAPI(title="FedCardio API", version="0.1.0",
              description="Privacy-preserving federated learning platform for cardiovascular risk "
                          "(**research demonstrator, not for clinical use**).")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type",
                                                                                     "X-Requested-With"])

_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def guard(request: Request, call_next):
    # simple sliding-window rate limit per client IP (stricter for login); use a shared store
    # (Redis) behind multiple replicas in production
    ip = request.client.host if request.client else "unknown"
    is_login = request.url.path.endswith("/auth/login") or request.url.path.endswith("/auth/mfa/verify")
    limit = settings.login_rate_limit_per_minute if is_login else settings.rate_limit_per_minute
    key = f"{ip}:{'login' if is_login else 'api'}"
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
    q.append(now)
    resp = await call_next(request)
    resp.headers.update({
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    })
    if settings.env != "dev":
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


for r in (auth.router, admin.router, datasets.router, patients.router, ml.router, fl.router):
    app.include_router(r)


@app.on_event("startup")
def startup():
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)  # postgres deployments use Alembic migrations
        add_missing_sqlite_columns()


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ready", "env": settings.env}
