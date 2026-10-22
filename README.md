# FedCardio

A privacy-preserving federated learning platform for cardiovascular risk. It is a **research demonstrator**:
not clinically validated, not certified, and not for patient-care decisions.

FedCardio re-implements the methods of Sharma et al., *Privacy-Preserving Federated Learning via Differential Privacy
and Homomorphic Encryption for Cardiovascular Disease Risk Modeling* (arXiv:2604.27598), on **public** data
(UCI Heart: 4 real hospitals; Cardio-70k: simulated hospitals). It then tests whether drift-aware FL, accounted DP,
secure aggregation, calibration and honest thresholds do better. The platform is wrapped in a web app for
clinicians, hospital admins, data scientists and auditors.

- Status, results and limitations: [PROGRESS.md](PROGRESS.md)
- Paper summary and discrepancies: [docs/SPEC.md](docs/SPEC.md)
- Threat model (what each privacy mechanism does and does not protect): [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)
- What it would take to become hospital-ready: [docs/PATH_TO_CLINICAL.md](docs/PATH_TO_CLINICAL.md)
- Data sources and datasheet: [data/README.md](data/README.md)
- Screenshots: [docs/screenshots/](docs/screenshots)

## Run it locally (Windows)

One-time setup:
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.lock -r backend\requirements.txt
.venv\Scripts\python -m fl_engine.data.download     # UCI Heart + Cardio-70k into data\raw (not committed)
.venv\Scripts\python -m backend.app.seed            # demo hospitals, users, synthetic patients
cd frontend; npm install; cd ..
```
Start both servers and open the browser:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_local.ps1
```
- App: http://localhost:3000 · API docs: http://127.0.0.1:8000/docs
- Demo accounts (password `FedCardio!2026`, synthetic data only): `dr.cleveland@fedcardio.dev` (clinician),
  `admin.hungarian@fedcardio.dev` (hospital admin), `ds@fedcardio.dev` (data scientist),
  `auditor@fedcardio.dev` (auditor), `admin@fedcardio.dev` (platform admin).

## Tests
```powershell
.venv\Scripts\python -m pytest tests backend\tests -p no:warnings --cov=fl_engine --cov=backend/app
cd frontend; npx playwright test          # needs both servers running; includes axe WCAG 2.2 AA checks
```

## Reproduce the experiments
```powershell
.venv\Scripts\python -m experiments.run_centralized --dataset uci --repeats 5 --folds 5 --budget 20
.venv\Scripts\python -m experiments.run_federated --suite uci --repeats 3     # also: noniid clients privacy imbalance
.venv\Scripts\python -m experiments.run_attacks
.venv\Scripts\python -m experiments.run_explain                               # fairness, SHAP, exports the served model
.venv\Scripts\python -m experiments.make_tables
```
Every output CSV is hashed into `results/manifest.json` with its git commit, parameters and data hashes.

## Layout
- `fl_engine/`: data, models, FL simulator (`sim.py`), privacy (SVT, DP-SGD+RDP, CKKS, SecAgg), attacks, evaluation, Flower app
- `experiments/`: experiment runners. `results/`: generated CSVs plus the manifest
- `backend/` (FastAPI): auth+MFA, RBAC, FHIR sharing with consent, envelope encryption, audit chain, model serving, FL jobs
- `frontend/` (Next.js + Tailwind): the web app, with Playwright E2E tests
- `models/registry/`: exported model cards and weights (JSON)
