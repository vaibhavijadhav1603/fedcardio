# FedCardio

A privacy-preserving federated learning platform for cardiovascular risk modelling. It is a **research demonstrator**:
not clinically validated, not certified, and not for clinical decisions.

FedCardio re-implements the methods of Sharma et al., *Privacy-Preserving Federated Learning via Differential Privacy
and Homomorphic Encryption for Cardiovascular Disease Risk Modeling* (arXiv:2604.27598), on **public** datasets, and
tests whether drift-aware FL, imbalance handling, calibration, accounted DP and secure aggregation improve on them.

Status: see [PROGRESS.md](PROGRESS.md). Paper summary and discrepancies: [docs/SPEC.md](docs/SPEC.md).
Data sources and datasheet: [data/README.md](data/README.md).

## Quick start
```bash
make setup     # venv + pinned deps
make data      # download UCI Heart + Cardio-70k into data/raw (not committed)
make test
```

## Layout
- `fl_engine/`: data, models, FL algorithms, privacy (DP/HE/SecAgg), attacks, evaluation
- `experiments/`: configs and runners. `results/`: script-generated CSVs plus a manifest
- `backend/` (FastAPI), `frontend/` (Next.js), `paper/` (LaTeX), `docs/`
