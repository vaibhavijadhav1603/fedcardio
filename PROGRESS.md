# PROGRESS

Last updated 2026-10-22. Runs on **localhost** (deployment deferred at the user's request). Writing our own paper is deferred too.

## Done
- **Phase 0**: paper read; `docs/SPEC.md` with 11 discrepancies (key one: the paper's code picks sensitivity/specificity thresholds
  in-sample, not at 0.5). Data: UCI Heart (4 real hospitals, n=920) and Cardio-70k (68,608 after cleaning).
- **Phase 1**: leakage-free preprocessing; model zoo (paper LR/NN re-implementations, tuned MLP, XGBoost, LightGBM, RF; equal
  Optuna budget); corrected CIs, corrected paired t-test + Holm, DeLong.
- **Phase 2**: FL simulator (FedAvg, FedProx, SCAFFOLD, FedAdam, FedBN, fine-tuning, local-only, client dropout); privacy modules
  (paper SVT filter, record-level DP-SGD with RDP accountant, CKKS via TenSEAL with paper parameters, additive-mask SecAgg,
  valid combinations DP+HE and DP+SecAgg); federated preprocessing from aggregate statistics; attacks (gradient inversion,
  membership inference); fairness and Shapley explanations; model export to `models/registry/`.
- **Phase 3**: FastAPI backend: password + TOTP MFA, short-lived JWT + rotating refresh cookie with reuse detection, 5-role RBAC
  (deny by default; platform admin has no patient access), per-hospital tenants, FHIR R4B patients/observations/consent,
  envelope encryption (AES-256-GCM, per-hospital KEK; file KMS stub marked insecure), consent → share → approve → view →
  revoke with key destruction, patient lookup by exact name + birth year + sex (MPI-style, audited, ambiguous matches refused) or by
  the ID on the patient's ID card, hash-chained audit log with tamper detection and CSV export, rate limiting, security headers,
  model serving (calibrated probability, threshold, Shapley drivers, OOD warning), model promote/rollback, FL job orchestration.
- **Phase 4**: Next.js + Tailwind web app: login + MFA; clinician risk dashboard (gauge, drivers, plain-language explanation,
  consent, FHIR view, feedback); record sharing; FL console with live curves and privacy-budget meter; experiments explorer;
  model registry with model cards; administration; audit viewer. Light/dark, responsive, strings externalised (English; Hindi/Kannada slots).

## Tests (real outputs)
- Engine: `pytest tests`: 22 (Phase 1) + 6 (zoo) + 16 (FL/privacy) tests, all passing. Includes FedAvg == centralised GD in the IID
  full-participation limit, CKKS error < 1e-4, SecAgg masks cancel, DP accountant monotone, SVT sparsity/clipping.
- Backend: `pytest backend/tests`: **85 passed** (role × endpoint matrix, tenant isolation, consent/revocation cascade,
  audit tamper detection, refresh-token reuse, MFA, prediction, an end-to-end HE training job).
- Frontend: Playwright, **7/7 flows passing** with axe WCAG 2.2 A/AA checks (no serious or critical violations). Axe found and I fixed
  low-contrast text, misused tabs and unlabeled charts.

## Key results (script-generated; see `results/`, the UI's Experiments page)
UCI, 3×5 per-site CV, AUROC (honest validation-chosen threshold):

| Paper method (re-implemented) | AUROC | Ours | AUROC |
|---|---|---|---|
| FedAvg-NN | 0.824 | SCAFFOLD-NN | **0.864** |
| SVT-DP NN (no formal guarantee) | 0.629 | DP-SGD NN, ε=3 (formal) | **0.840** |
| SVT-DP LR | 0.850 | DP-SGD LR, ε=3 | **0.868** |
| FedAvg-LR | 0.873 | FedProx-LR | 0.877 (not a meaningful gain) |
| cML-LR | **0.885** | best federated | 0.877 |

- HE matches plain FedAvg exactly (AUROC 0.824) at ~507× upload for packed CKKS (per-tensor is about 6× more again).
- Non-IID (Cardio-70k, α=0.1): FedAvg 0.640 → SCAFFOLD 0.776 pooled, 0.740 worst-site. FedBN's 0.963 pooled is an artifact of
  site base rates (worst-site 0.665).
- Privacy–utility (Cardio-70k): DP-SGD costs ≤0.005 AUROC from ε=0.5 to ∞ (0.786–0.787 vs 0.791). The paper's SVT collapses (0.493).
- Imbalance (6.4% prevalence): fixed 0.5 threshold gives sensitivity 0.000; a validation-chosen threshold gives 0.69 / 0.74 sens/spec.
  The paper's in-sample macro-F1 rule gives 0.38 / 0.93, which reproduces the paper's low-sensitivity pattern.
- Fairness: one threshold gives sensitivity 0.70 (women) vs 0.88 (men); specificity 0.33 at VA Long Beach.

**Honest bottom line:** our methods beat the paper's *federated and DP* re-implementations on the same data, but nothing beats a
centralised LR on UCI. All datasets differ from the paper's, so nothing here is comparable to its Table 2 in absolute terms.

## Deviations / limitations
- The Phase 1 Cardio baselines were cut from 2×5 folds and 20 trials to 1×5 folds and 10 trials (same budget for every model) after the
  first run exhausted RAM. The Phase 1 *centralised* UCI baseline files (`p1_uci_*.csv`) are **not in the repo**: a 5×5 / 20-trial
  run was done earlier in development but its outputs were deleted before a rerun that was not performed. The UCI centralised
  paper models (cML-LR, cML-NN) are still evaluated on identical folds inside the Phase 2 UCI suite (`p2_uci_folds.csv`).
  To regenerate: `python -m experiments.run_centralized --dataset uci --repeats 5 --folds 5 --budget 20`.
- FL runs use 50 rounds (paper: 250); FL-LR is a torch LR with AdamW, not warm-started liblinear.
- Pooled validation scores stand in for a federated ROC built from per-site score histograms.
- Membership inference was weak for all mechanisms; DP's effect was not separable from the training-regime change.
- Built-in OIDC-style auth instead of Keycloak (memory); the Flower networked app (`fl_engine/flower_app.py`) is written but
  **not yet run** end to end. The dev KMS is insecure by design. SecAgg has no dropout recovery.

## Next
- Docker/CI/deployment (deferred by the user), our paper draft (deferred), Keycloak, Flower multi-process demo run,
  Hindi/Kannada translations, `make_tables` for Phase 2 statistics.
