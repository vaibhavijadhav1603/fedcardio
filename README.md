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

Needs Python 3.11+, Node.js 20+ and git. One-time setup:
```powershell
git clone https://github.com/vaibhavijadhav1603/fedcardio.git
cd fedcardio
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
- Already have a clone? `git pull`, then rerun `.venv\Scripts\pip install -r backend\requirements.txt`,
  `.venv\Scripts\python -m backend.app.seed` (adds what is new without deleting anything) and `cd frontend; npm install`.

### A quick tour
1. **Data scientist** (`ds@`): Federated learning → start a job (e.g. Logistic regression, FedAvg, 20 rounds). When it is
   completed, **Register model** on the job card puts it in the Model registry as *staging*.
2. **Platform admin** (`admin@`): Model registry → promote that model to production; Administration → add a hospital.
3. **Hospital admin** (`admin.hungarian@`): Administration → add a clinician; Training data → upload a CSV.
4. **Clinician** (`dr.cleveland@`): Risk assessment → pick or add a patient, see the risk, its drivers and consent.
5. **Auditor** (`auditor@`): Audit log → every action above, hash-chained.

### Using your own hospitals
The 4 demo hospitals are only a starting point. As the platform admin (Administration → Hospitals) you can add hospitals,
**deactivate** one (its accounts are locked out, its FL node goes offline, open shares are closed; records are kept and it can be
re-activated) and then **delete** it permanently (type its tenant code to confirm; its patients, accounts, dataset and encryption
key are erased, the audit log is kept).

There is one platform admin. It creates each hospital together with that hospital's admin; the hospital admin then adds
the hospital's clinicians, and each clinician registers their own patients (Risk assessment → Add patient). Accounts made by an
admin get a temporary password and must choose their own at first sign-in; anyone can change theirs from the account menu, and
an admin can reset the password of the accounts they appoint (the platform admin can never reset a clinician's). The demo
account list on the login page is hidden: leave the email empty and type the demo password to reveal it.

Each hospital's admin uploads that hospital's training data under Administration → Training data: a CSV with the columns
`age, sex, cp, trestbps, chol, fbs, restecg, thalach, exang, oldpeak, target` (a template is downloadable there; at least
30 rows and 5 of each outcome). Ready-made synthetic examples are in `data/samples/`, and
`.venv\Scripts\python scripts\make_synthetic_csv.py out.csv 120 7` makes another (file, rows, seed). A registered patient also
becomes a training row when they have a confirmed or ruled-out diagnosis and an active **research** consent.

Federated jobs train on every active hospital that has data; at least 2 are needed. A finished job (LR or paper NN, not FedBN)
can be registered by the data scientist as a *staging* model; only the platform admin can promote it to production, after which
clinicians' risk predictions use it. To start with no demo hospitals at all:
```powershell
.venv\Scripts\python -m backend.app.seed --reset --no-demo   # only admin@, auditor@ and ds@ accounts
```
Running `python -m backend.app.seed` on a database made before this feature adds the demo hospitals' training data.

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
