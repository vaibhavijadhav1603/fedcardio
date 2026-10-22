# Path to clinical use

Current status: **research demonstrator.** Code alone does not make software hospital-ready. All of the following remain open.

| Area | What is needed | Status |
|---|---|---|
| Clinical validity | External and prospective validation on real hospital data, with the intended target (e.g. incident MI/HF), calibration and decision-curve analysis | Not started (public data only) |
| Ethics & governance | IRB/ethics approval, data-sharing agreements between hospitals, DPIA | Not started |
| Regulation (India) | DPDP Act 2023 compliance mapping, ABDM/NHA health data management policy, CDSCO Software-as-a-Medical-Device classification and approval | Not started |
| Regulation (other) | HIPAA / GDPR / EU MDR if deployed there | Not started |
| Security | Independent security audit and pen-test; real KMS/HSM instead of the file KMS stub; SecAgg dropout recovery; externally anchored audit head | Not started |
| Interoperability | Testing with real EHR / HL7 v2 / FHIR servers; terminology mapping (LOINC, SNOMED CT, ICD-10) | Prototype FHIR R4B resources only |
| Safety | Clinical safety case and hazard log; post-market monitoring; incident response plan | Not started |
| Human factors | Clinician usability studies; explanation comprehension testing | Not started |
| Monitoring | Bias/fairness monitoring per site and subgroup (sensitivity for women is lower today); data and model drift detection | Offline analysis only |
| Deployment | HTTPS, secrets management, backups, monitoring | Deferred; runs on localhost only |
