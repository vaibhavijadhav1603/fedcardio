import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="fedcardio-test-"))
os.environ["FEDCARDIO_DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["FEDCARDIO_KMS_DIR"] = str(_tmp / "kms")
os.environ["FEDCARDIO_TRAINED_MODELS_DIR"] = str(_tmp / "trained")
os.environ["FEDCARDIO_COOKIE_PATH"] = "/auth"
os.environ["FEDCARDIO_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["FEDCARDIO_LOGIN_RATE_LIMIT_PER_MINUTE"] = "100000"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app.seed import DEMO_PASSWORD, seed  # noqa: E402

seed(reset=True, patients_per_site=6)

USERS = {
    "platform_admin": "admin@fedcardio.dev",
    "hospital_admin": "admin.cleveland@fedcardio.dev",
    "clinician": "dr.cleveland@fedcardio.dev",
    "data_scientist": "ds@fedcardio.dev",
    "auditor": "auditor@fedcardio.dev",
}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def tokens(client):
    return {role: login(client, email) for role, email in USERS.items()} | {
        "clinician_hu": login(client, "dr.hungarian@fedcardio.dev"),
        "hospital_admin_hu": login(client, "admin.hungarian@fedcardio.dev"),
    }
