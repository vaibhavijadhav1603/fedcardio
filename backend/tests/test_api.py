import time

import pyotp
import pytest

from backend.app.db import SessionLocal
from backend.app.models import AuditEvent, Patient

from .conftest import USERS

ROLES = list(USERS)

# endpoint -> roles allowed (everything else must get 403). Deny by default.
MATRIX = [
    ("GET", "/patients", {"clinician", "hospital_admin"}),
    ("GET", "/predict/schema", {"clinician"}),
    ("POST", "/predict", {"clinician"}),
    ("GET", "/fl/nodes", {"platform_admin", "hospital_admin", "data_scientist", "auditor"}),
    ("GET", "/fl/jobs", {"platform_admin", "hospital_admin", "data_scientist", "auditor"}),
    ("GET", "/results/summary", set(ROLES)),
    ("GET", "/models", set(ROLES)),
    ("GET", "/audit", {"platform_admin", "hospital_admin", "auditor"}),
    ("GET", "/audit/verify", {"platform_admin", "hospital_admin", "auditor"}),
    ("GET", "/audit/export.csv", {"auditor"}),
    ("GET", "/users", {"platform_admin", "hospital_admin"}),
    ("GET", "/shares", {"clinician", "hospital_admin"}),
    ("POST", "/models/uci-logistic_regression-1.0.0/promote", {"platform_admin"}),
]


@pytest.mark.parametrize("method,path,allowed", MATRIX)
@pytest.mark.parametrize("role", ROLES)
def test_authorization_matrix(client, tokens, method, path, allowed, role):
    body = {"features": {"age": 55, "sex": 1, "cp": 4, "trestbps": 140}} if path == "/predict" else None
    r = client.request(method, path, headers=tokens[role], json=body)
    if role in allowed:
        assert r.status_code < 400, (role, path, r.status_code, r.text)
    else:
        assert r.status_code == 403, (role, path, r.status_code)


def test_unauthenticated_is_rejected(client):
    for path in ("/patients", "/audit", "/fl/jobs", "/models", "/auth/me"):
        assert client.get(path).status_code == 401


def test_platform_admin_cannot_read_patient_data(client, tokens):
    assert client.get("/patients", headers=tokens["platform_admin"]).status_code == 403


def test_bad_login_is_audited(client, tokens):
    r = client.post("/auth/login", json={"email": "dr.cleveland@fedcardio.dev", "password": "wrong"})
    assert r.status_code == 401
    items = client.get("/audit?action=auth.login&outcome=failure", headers=tokens["auditor"]).json()["items"]
    assert items and items[0]["outcome"] == "failure"


def test_tenant_isolation(client, tokens):
    hu_patients = client.get("/patients", headers=tokens["clinician_hu"]).json()
    pid = hu_patients[0]["id"]
    assert client.get(f"/patients/{pid}", headers=tokens["clinician"]).status_code == 404
    assert client.get(f"/patients/{pid}", headers=tokens["clinician_hu"]).status_code == 200


def test_patient_record_is_encrypted_at_rest_and_fhir_on_read(client, tokens):
    p = client.get("/patients", headers=tokens["clinician"]).json()[0]
    db = SessionLocal()
    row = db.get(Patient, p["id"])
    assert b"Observation" not in row.ciphertext and len(row.wrapped_dek) > 32
    db.close()
    full = client.get(f"/patients/{p['id']}", headers=tokens["clinician"]).json()
    assert full["fhir"]["resourceType"] == "Bundle"
    assert full["fhir"]["entry"][0]["resource"]["resourceType"] == "Patient"
    assert full["pseudo_id"].startswith("PX-")


def test_share_consent_approve_view_revoke_flow(client, tokens):
    # Cleveland clinician requests a Hungarian patient's record
    hu = client.get("/patients", headers=tokens["clinician_hu"]).json()
    target = hu[1]  # odd index -> seeded without consent
    pseudo = target["pseudo_id"]
    assert client.get(f"/patients/directory?pseudo_id={pseudo}", headers=tokens["clinician"]).status_code == 200
    r = client.post("/shares", headers=tokens["clinician"],
                    json={"pseudo_id": pseudo, "purpose": "treatment", "justification": "Patient transferred to our cardiology ward"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    # cannot view before approval
    assert client.get(f"/shares/{sid}/record", headers=tokens["clinician"]).status_code == 403
    # requester's admin cannot decide; owner's admin must
    assert client.post(f"/shares/{sid}/decide", headers=tokens["hospital_admin"], json={"approve": True}).status_code == 404
    # no consent yet -> approval refused
    assert client.post(f"/shares/{sid}/decide", headers=tokens["hospital_admin_hu"], json={"approve": True}).status_code == 409
    # owner hospital records consent, then approves
    c = client.post(f"/patients/{target['id']}/consents", headers=tokens["clinician_hu"],
                    json={"purpose": "treatment", "valid_days": 30})
    assert c.status_code == 201 and c.json()["fhir"]["resourceType"] == "Consent"
    d = client.post(f"/shares/{sid}/decide", headers=tokens["hospital_admin_hu"], json={"approve": True, "valid_days": 7})
    assert d.status_code == 200 and d.json()["status"] == "approved"
    rec = client.get(f"/shares/{sid}/record", headers=tokens["clinician"])
    assert rec.status_code == 200 and rec.json()["fhir"]["entry"][0]["resource"]["id"] == pseudo
    # another hospital cannot read it
    assert client.get(f"/shares/{sid}/record", headers=tokens["clinician_hu"]).status_code == 404
    # revoking consent cascades: the recipient loses access immediately
    client.post(f"/consents/{c.json()['id']}/revoke", headers=tokens["clinician_hu"])
    after = client.get(f"/shares/{sid}/record", headers=tokens["clinician"])
    assert after.status_code == 403
    shares = client.get("/shares?direction=outgoing", headers=tokens["clinician"]).json()
    assert next(s for s in shares if s["id"] == sid)["status"] == "revoked"


def test_owner_admin_can_revoke_share(client, tokens):
    hu = client.get("/patients", headers=tokens["clinician_hu"]).json()
    target = hu[3]
    client.post(f"/patients/{target['id']}/consents", headers=tokens["clinician_hu"], json={"purpose": "care_coordination"})
    sid = client.post("/shares", headers=tokens["clinician"], json={"pseudo_id": target["pseudo_id"],
                      "purpose": "care_coordination", "justification": "Shared care plan for follow-up"}).json()["id"]
    client.post(f"/shares/{sid}/decide", headers=tokens["hospital_admin_hu"], json={"approve": True})
    assert client.get(f"/shares/{sid}/record", headers=tokens["clinician"]).status_code == 200
    assert client.post(f"/shares/{sid}/revoke", headers=tokens["hospital_admin_hu"]).json()["status"] == "revoked"
    assert client.get(f"/shares/{sid}/record", headers=tokens["clinician"]).status_code == 403


def test_input_validation(client, tokens):
    assert client.post("/shares", headers=tokens["clinician"], json={"pseudo_id": "x", "purpose": "marketing",
                                                                     "justification": "short"}).status_code == 422
    assert client.post("/predict", headers=tokens["clinician"], json={"features": {"age": 400}}).status_code == 422
    assert client.post("/predict", headers=tokens["clinician"], json={"features": {"evil": 1}}).status_code == 422


def test_predict_by_patient_and_audit(client, tokens):
    p = client.get("/patients", headers=tokens["clinician"]).json()[0]
    r = client.post("/predict", headers=tokens["clinician"], json={"patient_id": p["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert 0 <= out["probability"] <= 1 and out["decision"] in ("above_threshold", "below_threshold")
    assert out["contributions"] and out["model_id"].startswith("uci-")
    assert "Research prototype" in out["disclaimer"]
    ev = client.get("/audit?action=model.predict", headers=tokens["auditor"]).json()["items"][0]
    assert ev["resource"] == f"patient:{p['pseudo_id']}"


def test_ood_warning(client, tokens):
    r = client.post("/predict", headers=tokens["clinician"],
                    json={"features": {"age": 99, "sex": 1, "trestbps": 239, "chol": 640, "thalach": 61, "oldpeak": 6.9}})
    assert r.status_code == 200 and isinstance(r.json()["ood_warning"], bool)


def test_audit_chain_detects_tampering(client, tokens):
    assert client.get("/audit/verify", headers=tokens["auditor"]).json()["valid"] is True
    db = SessionLocal()
    ev = db.query(AuditEvent).order_by(AuditEvent.seq).offset(2).first()
    original = ev.resource
    ev.resource = "tampered"
    db.commit()
    v = client.get("/audit/verify", headers=tokens["auditor"]).json()
    assert v["valid"] is False and v["first_bad_seq"] == ev.seq
    ev.resource = original
    db.commit()
    db.close()
    assert client.get("/audit/verify", headers=tokens["auditor"]).json()["valid"] is True


def test_refresh_rotation_and_reuse_detection(client):
    client.cookies.clear()
    client.post("/auth/login", json={"email": USERS["auditor"], "password": "FedCardio!2026"})
    first = client.cookies.get("fc_refresh")
    assert client.post("/auth/refresh").status_code == 403  # CSRF header required
    h = {"X-Requested-With": "fedcardio"}
    r = client.post("/auth/refresh", headers=h)
    assert r.status_code == 200 and client.cookies.get("fc_refresh") != first
    second = client.cookies.get("fc_refresh")
    client.cookies.set("fc_refresh", first, path="/auth")
    assert client.post("/auth/refresh", headers=h).status_code == 401  # reuse of rotated token
    client.cookies.set("fc_refresh", second, path="/auth")
    assert client.post("/auth/refresh", headers=h).status_code == 401  # whole family revoked


def test_mfa_enrolment_and_login(client):
    from .conftest import login
    hdr = login(client, "admin.switzerland@fedcardio.dev")
    secret = client.post("/auth/mfa/setup", headers=hdr).json()["secret"]
    assert client.post("/auth/mfa/enable", headers=hdr, json={"code": "000000"}).status_code == 400
    assert client.post("/auth/mfa/enable", headers=hdr, json={"code": pyotp.TOTP(secret).now()}).json()["mfa_enabled"]
    r = client.post("/auth/login", json={"email": "admin.switzerland@fedcardio.dev", "password": "FedCardio!2026"})
    assert r.json()["mfa_required"] is True
    bad = client.post("/auth/mfa/verify", json={"challenge": r.json()["challenge"], "code": "123456"})
    assert bad.status_code == 401
    ok = client.post("/auth/mfa/verify", json={"challenge": r.json()["challenge"], "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_user_management_scoping(client, tokens):
    r = client.post("/users", headers=tokens["hospital_admin"], json={
        "email": "new.nurse@fedcardio.dev", "full_name": "New Nurse", "role": "clinician", "hospital_id": 2,
        "password": "a-long-password-123"})
    assert r.status_code == 403  # other tenant
    r = client.post("/users", headers=tokens["hospital_admin"], json={
        "email": "evil@fedcardio.dev", "full_name": "Evil", "role": "platform_admin", "hospital_id": 1,
        "password": "a-long-password-123"})
    assert r.status_code == 403  # privilege escalation
    r = client.post("/users", headers=tokens["hospital_admin"], json={
        "email": "new.doc@fedcardio.dev", "full_name": "New Doc", "role": "clinician", "hospital_id": 1,
        "password": "a-long-password-123"})
    assert r.status_code == 201


def test_model_promote_and_rollback(client, tokens):
    models = client.get("/models", headers=tokens["platform_admin"]).json()
    assert models[0]["card"]["intended_use"].startswith("Research")
    assert "weights" not in models[0]["card"]
    r = client.post(f"/models/{models[0]['id']}/rollback", headers=tokens["platform_admin"])
    assert r.status_code == 409  # only one version exists


def test_fl_job_runs_end_to_end(client, tokens):
    r = client.post("/fl/jobs", headers=tokens["data_scientist"],
                    json={"model": "lr", "algorithm": "fedavg", "privacy": "he", "rounds": 3, "local_epochs": 2})
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    assert client.post("/fl/jobs", headers=tokens["data_scientist"],
                       json={"algorithm": "scaffold", "privacy": "dpsgd"}).status_code == 422
    for _ in range(120):
        j = client.get(f"/fl/jobs/{jid}", headers=tokens["data_scientist"]).json()
        if j["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "completed", j["error"]
    assert len(j["history"]) == 3 and 0 < j["metrics"]["auroc"] <= 1 and j["metrics"]["he_max_abs_error"] < 1e-3


def test_results_summary_and_file_download(client, tokens):
    s = client.get("/results/summary", headers=tokens["data_scientist"]).json()
    assert "paper_table2" in s and len(s["paper_table2"]) == 8
    assert client.get("/results/files/..%2F.env", headers=tokens["data_scientist"]).status_code == 404


def test_security_headers_and_health(client):
    r = client.get("/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"


def test_logout_revokes_session(client):
    client.cookies.clear()
    client.post("/auth/login", json={"email": USERS["clinician"], "password": "FedCardio!2026"})
    assert client.post("/auth/logout").json() == {"ok": True}
    assert client.post("/auth/refresh", headers={"X-Requested-With": "fedcardio"}).status_code == 401


def test_match_lookup_by_name_birth_year_sex(client, tokens):
    target = client.get("/patients", headers=tokens["clinician_hu"]).json()[0]
    q = {"name": f"  {target['display_name'].upper()} ", "birth_year": target["birth_year"], "sex": target["sex"]}
    r = client.get("/patients/match", params=q, headers=tokens["clinician"])
    assert r.status_code == 200 and r.json()["pseudo_id"] == target["pseudo_id"]
    # wrong birth year or partial name -> no match; own hospital's patients are never returned
    assert client.get("/patients/match", params={**q, "birth_year": target["birth_year"] + 1},
                      headers=tokens["clinician"]).status_code == 404
    assert client.get("/patients/match", params={**q, "name": target["display_name"].split()[0]},
                      headers=tokens["clinician"]).status_code == 404
    assert client.get("/patients/match", params=q, headers=tokens["clinician_hu"]).status_code == 404
    # roles without share:request are refused
    assert client.get("/patients/match", params=q, headers=tokens["auditor"]).status_code == 403
