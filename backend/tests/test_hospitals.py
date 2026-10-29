"""Hospital lifecycle (add, deactivate, reactivate, delete) and per-hospital training data upload."""
import time

from backend.app import datasets
from backend.app.config import get_settings
from backend.app.seed import DEMO_PASSWORD, _uci

from .conftest import login

PW = "Hospital!2026x"


def _csv(code="hungarian", n=None, target="target"):
    df = _uci()
    g = df.loc[df.site == code, datasets.FEATURES + ["y"]].head(n).rename(columns={"y": target})
    return g.to_csv(index=False)


def _with_first_age(csv, age):
    head, first, rest = csv.split("\n", 2)
    return "\n".join([head, age + first[first.index(","):], rest])


def _new_hospital(client, tokens, code):
    """The platform admin creates the hospital with its admin; that admin then adds the clinician."""
    dom = code.replace("_", "-")
    r = client.post("/hospitals", headers=tokens["platform_admin"], json={
        "code": code, "name": f"Test {code}", "city": "Pune",
        "admin": {"email": f"admin@{dom}.fedcardio.dev", "full_name": f"Admin {code}", "password": PW}})
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    admin = login_pw(client, f"admin@{dom}.fedcardio.dev")
    u = client.post("/users", headers=admin, json={"email": f"dr@{dom}.fedcardio.dev", "full_name": f"Dr {code}",
                                                   "role": "clinician", "hospital_id": hid, "password": PW})
    assert u.status_code == 201, u.text
    return hid, admin, login_pw(client, f"dr@{dom}.fedcardio.dev")


def login_pw(client, email):
    r = client.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_csv_validation():
    assert len(datasets.parse_csv(_csv())) == 294
    assert datasets.parse_csv(_csv(target="num")).y.isin((0, 1)).all()
    for bad, msg in [
        ("age,sex\n50,1\n", "missing columns"),
        (_csv(n=10), "at least 30 rows"),
        (_with_first_age(_csv(), "140"), "line 2: age=140 is out of range"),
        (_with_first_age(_csv(), "forty"), "line 2: age is not a number"),
    ]:
        try:
            datasets.parse_csv(bad)
        except datasets.DatasetError as e:
            assert msg in str(e), (msg, str(e))
        else:
            raise AssertionError(f"accepted CSV that should fail with {msg!r}")


def test_only_own_hospital_admin_can_upload(client, tokens):
    body = {"filename": "x.csv", "csv": _csv()}
    for role in ("platform_admin", "clinician", "data_scientist", "auditor"):
        assert client.post("/datasets/mine", headers=tokens[role], json=body).status_code == 403
    r = client.post("/datasets/mine", headers=tokens["hospital_admin"], json={"filename": "x.csv", "csv": "age\n1\n"})
    assert r.status_code == 422 and "missing columns" in r.json()["detail"]


def test_new_hospital_uploads_data_and_joins_training(client, tokens):
    hid, admin, _ = _new_hospital(client, tokens, "pune_city")
    nodes = {n["hospital_id"] for n in client.get("/fl/nodes", headers=tokens["data_scientist"]).json()}
    assert hid not in nodes  # no data yet -> not an FL client
    r = client.post("/datasets/mine", headers=admin, json={"filename": "pune.csv", "csv": _csv("hungarian")})
    assert r.status_code == 201, r.text
    assert r.json()["dataset"]["n_rows"] == 294
    assert client.get("/datasets/mine", headers=admin).json()["dataset"]["filename"] == "pune.csv"
    node = next(n for n in client.get("/fl/nodes", headers=tokens["data_scientist"]).json() if n["hospital_id"] == hid)
    assert node["status"] == "online" and node["n_records"] == 294
    h = next(x for x in client.get("/hospitals", headers=tokens["platform_admin"]).json() if x["id"] == hid)
    assert h["dataset"]["n_rows"] == 294 and h["n_users"] == 2

    j = client.post("/fl/jobs", headers=tokens["data_scientist"], json={"model": "lr", "rounds": 2, "local_epochs": 1})
    assert j.status_code == 201, j.text
    for _ in range(120):
        job = client.get(f"/fl/jobs/{j.json()['id']}", headers=tokens["data_scientist"]).json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert job["status"] == "completed", job["error"]
    assert job["metrics"]["n_sites"] == 5 and "auroc_pune_city" in job["metrics"]

    assert client.delete("/datasets/mine", headers=admin).status_code == 200
    assert hid not in {d["hospital_id"] for d in client.get("/fl/nodes", headers=tokens["data_scientist"]).json()
                       if d["status"] == "online"}


def test_deactivate_reactivate_and_delete(client, tokens):
    hid, admin, dr = _new_hospital(client, tokens, "nashik")
    assert client.post("/datasets/mine", headers=admin, json={"filename": "n.csv", "csv": _csv("cleveland")}).status_code == 201
    p = client.post("/patients", headers=dr, json={"local_id": "N-1", "display_name": "Test Patient", "sex": "female",
                                                    "birth_year": 1970, "features": {"chol": 200}})
    assert p.status_code == 201, p.text
    pseudo = p.json()["pseudo_id"]
    share = client.post("/shares", headers=tokens["clinician"],
                        json={"pseudo_id": pseudo, "purpose": "treatment", "justification": "Transferred to Cleveland"})
    assert share.status_code == 201

    # only the platform admin manages hospitals; delete needs deactivation first
    assert client.post(f"/hospitals/{hid}/deactivate", headers=tokens["hospital_admin"]).status_code == 403
    assert client.delete(f"/hospitals/{hid}?confirm=nashik", headers=tokens["platform_admin"]).status_code == 409

    r = client.post(f"/hospitals/{hid}/deactivate", headers=tokens["platform_admin"])
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.get("/datasets/mine", headers=admin).status_code == 401  # live token stops working
    r = client.post("/auth/login", json={"email": "admin@nashik.fedcardio.dev", "password": PW})
    assert r.status_code == 403 and "deactivated" in r.json()["detail"]
    assert hid not in {h["id"] for h in client.get("/hospitals", headers=tokens["clinician"]).json()}
    assert hid not in {n["hospital_id"] for n in client.get("/fl/nodes", headers=tokens["data_scientist"]).json()}
    assert client.get(f"/patients/directory?pseudo_id={pseudo}", headers=tokens["clinician"]).status_code == 404
    mine = {s["id"]: s for s in client.get("/shares", headers=tokens["clinician"]).json()}
    assert mine[share.json()["id"]]["status"] == "denied"
    assert client.post("/users", headers=tokens["platform_admin"], json={
        "email": "late@nashik.fedcardio.dev", "full_name": "Late", "role": "hospital_admin", "hospital_id": hid, "password": PW,
    }).status_code == 409

    assert client.post(f"/hospitals/{hid}/reactivate", headers=tokens["platform_admin"]).status_code == 200
    login_pw(client, "admin@nashik.fedcardio.dev")
    assert client.post(f"/hospitals/{hid}/deactivate", headers=tokens["platform_admin"]).status_code == 200

    assert client.delete(f"/hospitals/{hid}?confirm=wrong", headers=tokens["platform_admin"]).status_code == 400
    kek = get_settings().kms_dir / "nashik.kek"
    assert kek.exists()
    r = client.delete(f"/hospitals/{hid}?confirm=nashik", headers=tokens["platform_admin"])
    assert r.status_code == 200, r.text
    assert not kek.exists()  # crypto-shredded
    assert hid not in {h["id"] for h in client.get("/hospitals", headers=tokens["platform_admin"]).json()}
    assert client.post("/auth/login", json={"email": "dr@nashik.fedcardio.dev", "password": PW}).status_code == 401
    assert share.json()["id"] not in {s["id"] for s in client.get("/shares", headers=tokens["clinician"]).json()}
    assert client.get("/audit/verify", headers=tokens["auditor"]).json()["valid"] is True
    actions = [e["action"] for e in client.get("/audit?action=hospital.", headers=tokens["auditor"]).json()["items"]]
    assert "hospital.delete" in actions


def test_training_needs_two_hospitals_with_data(client, tokens):
    hs = [h for h in client.get("/hospitals", headers=tokens["platform_admin"]).json() if h["active"] and h["dataset"]]
    for h in hs[1:]:
        assert client.post(f"/hospitals/{h['id']}/deactivate", headers=tokens["platform_admin"]).status_code == 200
    try:
        r = client.post("/fl/jobs", headers=tokens["data_scientist"], json={"model": "lr", "rounds": 1})
        assert r.status_code == 409 and "at least 2" in r.json()["detail"]
    finally:
        for h in hs[1:]:
            client.post(f"/hospitals/{h['id']}/reactivate", headers=tokens["platform_admin"])
    login(client, "dr.hungarian@fedcardio.dev")  # demo accounts work again after reactivation
    assert DEMO_PASSWORD


def test_role_appointment_rules(client, tokens):
    def make(who, role, hid, email):
        return client.post("/users", headers=tokens[who], json={
            "email": email, "full_name": "Someone", "role": role, "hospital_id": hid, "password": PW}).status_code
    cle = client.get("/auth/me", headers=tokens["hospital_admin"]).json()["hospital_id"]
    assert make("platform_admin", "platform_admin", None, "pa2@fedcardio.dev") == 403  # only one platform admin
    assert make("platform_admin", "clinician", cle, "doc1@fedcardio.dev") == 403      # hospital admins appoint doctors
    assert make("platform_admin", "hospital_admin", None, "ha1@fedcardio.dev") == 422  # must belong to a hospital
    assert make("platform_admin", "auditor", cle, "au1@fedcardio.dev") == 422         # platform-level role
    assert make("platform_admin", "hospital_admin", cle, "ha2@fedcardio.dev") == 201
    assert make("hospital_admin", "data_scientist", cle, "ds2@fedcardio.dev") == 403
    assert make("hospital_admin", "clinician", cle, "doc2@fedcardio.dev") == 201
    doc = next(u for u in client.get("/users", headers=tokens["platform_admin"]).json() if u["email"] == "doc2@fedcardio.dev")
    assert client.patch(f"/users/{doc['id']}", headers=tokens["platform_admin"], json={"role": "platform_admin"}).status_code == 403
    assert client.patch(f"/users/{doc['id']}", headers=tokens["platform_admin"], json={"active": False}).status_code == 200


def test_demo_accounts_list_only_existing_accounts(client):
    # hidden unless the demo password is given
    assert client.get("/auth/demo-accounts").status_code == 405
    assert client.post("/auth/demo-accounts", json={"password": "guess"}).status_code == 404
    accounts = client.post("/auth/demo-accounts", json={"password": DEMO_PASSWORD}).json()
    emails = {a["email"] for a in accounts}
    assert {"admin@fedcardio.dev", "ds@fedcardio.dev", "auditor@fedcardio.dev"} <= emails
    assert "dr@nashik.fedcardio.dev" not in emails  # deleted with its hospital
    assert sum(a["role"] == "clinician" and a["hospital"] == "Hungarian Institute of Cardiology" for a in accounts) == 1


def test_password_change_and_admin_reset(client, tokens):
    hid, admin, dr = _new_hospital(client, tokens, "satara")
    me = client.get("/auth/me", headers=dr).json()
    assert me["must_change_password"] is False  # no forced change of an admin-issued password
    assert client.post("/auth/password", headers=dr, json={"current_password": "wrong-one-xx", "new_password": "Mine!2026xyz"}).status_code == 400
    r = client.post("/auth/password", headers=dr, json={"current_password": PW, "new_password": "Mine!2026xyz"})
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert client.post("/auth/login", json={"email": "dr@satara.fedcardio.dev", "password": PW}).status_code == 401
    assert client.post("/auth/login", json={"email": "dr@satara.fedcardio.dev", "password": "Mine!2026xyz"}).status_code == 200
    assert client.post("/auth/password", headers=dr, json={"current_password": "Mine!2026xyz", "new_password": "abcd"}).status_code == 422
    assert client.post("/auth/password", headers=dr, json={"current_password": "Mine!2026xyz", "new_password": "abcde"}).status_code == 200
    assert client.post("/auth/login", json={"email": "dr@satara.fedcardio.dev", "password": "abcde"}).status_code == 200

    uid = me["id"]
    # the platform admin cannot take over a clinician account (that would reach patient data)
    assert client.post(f"/users/{uid}/password", headers=tokens["platform_admin"], json={"password": "Reset!2026xx"}).status_code == 403
    assert client.post(f"/users/{uid}/password", headers=tokens["hospital_admin"], json={"password": "Reset!2026xx"}).status_code == 403
    r = client.post(f"/users/{uid}/password", headers=admin, json={"password": "Reset!2026xx"})
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert client.post("/auth/login", json={"email": "dr@satara.fedcardio.dev", "password": "Reset!2026xx"}).status_code == 200
    admin_id = client.get("/auth/me", headers=admin).json()["id"]
    assert client.post(f"/users/{admin_id}/password", headers=tokens["platform_admin"], json={"password": "Reset!2026yy"}).status_code == 200


def test_role_launcher(client, tokens):
    client.cookies.clear()
    assert client.get("/auth/launcher").status_code == 401
    # a non-admin sign-in does not open the launcher
    client.post("/auth/login", json={"email": "ds@fedcardio.dev", "password": DEMO_PASSWORD})
    assert client.get("/auth/launcher").status_code == 401
    client.post("/auth/login", json={"email": "admin@fedcardio.dev", "password": DEMO_PASSWORD})
    groups = client.get("/auth/launcher").json()
    assert {u["role"] for u in groups["platform"]} == {"platform_admin", "data_scientist", "auditor"}
    cle = next(h for h in groups["hospitals"] if h["name"].startswith("Cleveland"))
    dr = next(u for u in cle["users"] if u["role"] == "clinician")
    r = client.post("/auth/launcher/enter", json={"user_id": dr["id"]})
    assert r.status_code == 200 and r.json()["user"]["role"] == "clinician"
    hdr = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auth/me", headers=hdr).json()["email"] == dr["email"]
    # switching again needs no password, and the launcher survives a role's sign-out
    client.post("/auth/logout")
    ds = next(u for u in groups["platform"] if u["role"] == "data_scientist")
    assert client.post("/auth/launcher/enter", json={"user_id": ds["id"]}).json()["user"]["role"] == "data_scientist"
    # an account created without a password can still be entered from the launcher
    h = client.post("/hospitals", headers=tokens["platform_admin"], json={
        "code": "wardha", "name": "Wardha Heart", "admin": {"full_name": "No Password", "email": "admin@wardha.fedcardio.dev"}})
    assert h.status_code == 201
    new = next(x for x in client.get("/auth/launcher").json()["hospitals"] if x["id"] == h.json()["id"])["users"][0]
    assert client.post("/auth/launcher/enter", json={"user_id": new["id"]}).json()["user"]["role"] == "hospital_admin"
    assert client.post("/auth/launcher/close").status_code == 200
    assert client.get("/auth/launcher").status_code == 401
    client.cookies.clear()


def test_registered_patients_become_training_rows(client, tokens):
    hid, admin, dr = _new_hospital(client, tokens, "kolhapur")
    df = _uci().query("site == 'cleveland'").head(36).reset_index(drop=True)
    for i, r in df.iterrows():
        feats = {k: (None if r[k] != r[k] else float(r[k])) for k in ("trestbps", "chol", "thalach", "oldpeak", "fbs", "exang", "cp", "restecg")}
        p = client.post("/patients", headers=dr, json={
            "local_id": f"K-{i}", "display_name": f"Kolhapur Patient {i}", "sex": "male" if r.sex == 1 else "female",
            "birth_year": 2026 - int(r.age), "features": feats, "diagnosis": int(r.y)})
        assert p.status_code == 201, p.text
        if i < 34:  # two patients without research consent must not be used
            c = client.post(f"/patients/{p.json()['id']}/consents", headers=dr, json={"purpose": "research", "valid_days": 30})
            assert c.status_code == 201
    info = client.get("/datasets/mine", headers=admin).json()
    assert info["dataset"] is None and info["rows_from_csv"] == 0
    assert info["rows_from_patients"] == 34 and info["usable"] is True
    node = next(n for n in client.get("/fl/nodes", headers=tokens["data_scientist"]).json() if n["hospital_id"] == hid)
    assert node["status"] == "online" and node["n_records"] == 34
    assert client.post("/patients", headers=dr, json={"local_id": "K-future", "display_name": "Future Kid", "sex": "male",
                                                      "birth_year": 2999}).status_code == 422
    assert client.post(f"/hospitals/{hid}/deactivate", headers=tokens["platform_admin"]).status_code == 200


def test_finished_job_model_can_be_registered_and_promoted(client, tokens):
    j = client.post("/fl/jobs", headers=tokens["data_scientist"], json={"model": "lr", "rounds": 2, "local_epochs": 1})
    assert j.status_code == 201, j.text
    jid = j.json()["id"]
    for _ in range(120):
        job = client.get(f"/fl/jobs/{jid}", headers=tokens["data_scientist"]).json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert job["status"] == "completed", job["error"]
    assert job["registrable"] is True and job["registered_model"] is None
    assert client.post(f"/fl/jobs/{jid}/register", headers=tokens["platform_admin"]).status_code == 403
    r = client.post(f"/fl/jobs/{jid}/register", headers=tokens["data_scientist"])
    assert r.status_code == 201 and r.json()["registered_model"] == f"fl-job-{jid}-logistic_regression"
    assert client.post(f"/fl/jobs/{jid}/register", headers=tokens["data_scientist"]).status_code == 409
    mid = r.json()["registered_model"]
    m = client.get(f"/models/{mid}", headers=tokens["platform_admin"]).json()
    assert m["stage"] == "staging" and 0 < m["card"]["validation_metrics"]["auroc"] <= 1
    # the platform admin approves it; clinicians' predictions then come from this model
    assert client.post(f"/models/{mid}/promote", headers=tokens["platform_admin"]).status_code == 200
    pid = client.get("/patients", headers=tokens["clinician"]).json()[0]["id"]
    pred = client.post("/predict", headers=tokens["clinician"], json={"patient_id": pid})
    assert pred.status_code == 200, pred.text
    assert client.post(f"/models/{mid}/rollback", headers=tokens["platform_admin"]).status_code == 200
