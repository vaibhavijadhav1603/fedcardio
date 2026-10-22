# PROGRESS

## Phase 0: spec, skeleton, data access (DONE, 2026-10-22)

**Done**
- Read the full paper (14 pp) and the public code (`fl_with_pets`, main branch). Wrote `docs/SPEC.md` with page refs
  and 11 discrepancies (brief vs PDF, PDF vs code).
- Key finding: the paper's code chooses sensitivity/specificity thresholds **in-sample** (Youden for NN, macro-F1 for LR).
  It does not use a fixed 0.5 threshold, as the brief assumed.
- Repo skeleton, venv (Python 3.11), pinned lockfile `requirements.lock`.
- Data: UCI Heart (4 real hospitals, 920 rows) and Cardio-70k (68,608 after cleaning) download and load.
  Hashes are in `data/raw/MANIFEST.json`.
- FL framework decision: a pure-PyTorch simulator for experiments, plus Flower 1.41 for the dockerised multi-node demo.
  NVFlare is not used (heavy on Windows; the paper's SVT filter is re-implemented independently).

**Defaults taken**
- `docs/paper.pdf` is gitignored (licence of redistribution not checked); place it there manually.
- Cardio-70k licence is "Unknown" on Kaggle, so it is downloaded at run time and never redistributed.
- UCI: `slope`, `ca`, `thal` dropped from the main analysis (missing >50 % at ≥2 sites); kept in an ablation.

**Blocked / limitations**
- OpenML API timed out from this network (not needed; Kaggle and UCI work).
- The tasks differ from the paper (prevalent CAD / CVD presence vs 4-year incident MI/HF), so numbers are not comparable.

**Next (Phase 1)**: preprocessing with train-only fitting, Dirichlet partitioner, centralised baselines, paper re-implementation
(LR liblinear + 10-5-1 LayerNorm NN with AdamW), 5×5 repeated CV, baseline table.
