from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FEDCARDIO_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = f"sqlite:///{ROOT / 'backend' / 'fedcardio.db'}"
    jwt_secret: str = "dev-only-change-me-" + "x" * 32  # overridden via env in any real deployment
    jwt_issuer: str = "fedcardio"
    access_ttl_minutes: int = 15
    refresh_ttl_hours: int = 8
    # Optional external OIDC provider (e.g. Keycloak). When set, bearer tokens signed by its JWKS are accepted.
    oidc_issuer: str | None = None
    oidc_audience: str = "fedcardio"
    kms_dir: Path = ROOT / "backend" / ".dev-kms"   # INSECURE file-based KMS stub (dev only)
    pseudonym_key: str = "dev-pseudonym-key-change-me"
    registry_dir: Path = ROOT / "models" / "registry"
    trained_models_dir: Path = ROOT / "models" / "trained"  # cards of models trained from the console (not in git)
    results_dir: Path = ROOT / "results"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    rate_limit_per_minute: int = 120
    login_rate_limit_per_minute: int = 10
    demo_password: str = "FedCardio!2026"  # dev only: seeded demo accounts use it, and it unlocks the login page list
    require_mfa_roles: list[str] = []  # e.g. ["platform_admin"] in production
    cookie_path: str = "/api/auth"  # path the browser sees through the frontend proxy


@lru_cache
def get_settings() -> Settings:
    return Settings()
