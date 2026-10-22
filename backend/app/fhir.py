"""FHIR R4B resources (wire-compatible with R4 for the resources used) for patient records.

Identifiers are pseudonymous. LOINC codes are used where a standard code exists; other
UCI attributes use a local code system (http://fedcardio.example/codes).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.consent import Consent as FhirConsent
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient as FhirPatient

LOCAL = "http://fedcardio.example/codes"
LOINC = "http://loinc.org"

OBS_CODES = {
    "trestbps": (LOINC, "8480-6", "Systolic blood pressure (resting)", "mm[Hg]"),
    "chol": (LOINC, "2093-3", "Cholesterol [Mass/volume] in Serum or Plasma", "mg/dL"),
    "thalach": (LOINC, "8867-4", "Heart rate (maximum achieved, exercise test)", "/min"),
    "oldpeak": (LOCAL, "st-depression", "ST depression induced by exercise relative to rest", "mm"),
    "fbs": (LOCAL, "fbs-gt-120", "Fasting blood sugar > 120 mg/dL", "{boolean}"),
    "exang": (LOCAL, "exercise-angina", "Exercise induced angina", "{boolean}"),
    "cp": (LOCAL, "chest-pain-type", "Chest pain type (1 typical, 2 atypical, 3 non-anginal, 4 asymptomatic)", "{code}"),
    "restecg": (LOCAL, "rest-ecg", "Resting ECG (0 normal, 1 ST-T abnormality, 2 LVH)", "{code}"),
}


def patient_bundle(pseudo_id: str, sex: str, birth_year: int, features: dict, hospital_code: str) -> dict:
    pat = FhirPatient(
        id=pseudo_id,
        identifier=[{"system": f"urn:fedcardio:{hospital_code}:pseudonym", "value": pseudo_id}],
        gender="male" if sex == "male" else "female",
        birthDate=f"{birth_year}",
        meta={"security": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "PSEUDED"}]},
    )
    entries = [{"fullUrl": f"urn:uuid:patient-{pseudo_id}", "resource": pat}]
    now = datetime.now(timezone.utc).isoformat()
    for key, (system, code, display, unit) in OBS_CODES.items():
        val = features.get(key)
        if val is None:
            continue
        obs = Observation(
            id=f"{pseudo_id}-{key}", status="final",
            code={"coding": [{"system": system, "code": code, "display": display}], "text": display},
            subject={"reference": f"Patient/{pseudo_id}"}, effectiveDateTime=now,
            valueQuantity={"value": float(val), "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
        )
        entries.append({"fullUrl": f"urn:uuid:obs-{pseudo_id}-{key}", "resource": obs})
    return Bundle(type="collection", entry=entries).model_dump(mode="json")


def features_from_bundle(bundle: dict) -> dict:
    out: dict = {}
    code_to_key = {code: key for key, (_, code, _, _) in OBS_CODES.items()}
    for e in bundle.get("entry", []):
        r = e["resource"]
        if r["resourceType"] == "Observation":
            code = r["code"]["coding"][0]["code"]
            if code in code_to_key:
                out[code_to_key[code]] = r["valueQuantity"]["value"]
        elif r["resourceType"] == "Patient":
            out["sex"] = 1.0 if r.get("gender") == "male" else 0.0
            out["birth_year"] = int(r["birthDate"][:4])
    return out


def consent_resource(consent_id: int, pseudo_id: str, purpose: str, granted_to: str | None, until: datetime,
                     revoked: bool) -> dict:
    c = FhirConsent(
        id=f"consent-{consent_id}", status="inactive" if revoked else "active",
        scope={"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                           "code": "patient-privacy"}]},
        category=[{"coding": [{"system": "http://loinc.org", "code": "59284-0", "display": "Patient Consent"}]}],
        patient={"reference": f"Patient/{pseudo_id}"},
        policyRule={"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "OPTIN"}]},
        provision={"type": "permit", "period": {"end": until.isoformat()},
                   "purpose": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
                                "code": {"treatment": "TREAT", "research": "HRESCH",
                                         "care_coordination": "COC"}.get(purpose, "TREAT")}],
                   **({"actor": [{"role": {"coding": [{"code": "IRCP"}]},
                                  "reference": {"display": granted_to}}]} if granted_to else {})},
    )
    return c.model_dump(mode="json")
