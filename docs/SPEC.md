# SPEC — Base paper summary, discrepancies, and our reproduction target

Base paper: G. Sharma, J. Pajula, A. Illikainen, M. Rautell, N. Lipsonen, P. Alhainen, M. Hilvo,
"Privacy-Preserving Federated Learning via Differential Privacy and Homomorphic Encryption for
Cardiovascular Disease Risk Modeling", arXiv:2604.27598v1 [cs.LG], 30 Apr 2026 (14 pp).
Local copy: `docs/paper.pdf`. Public code: https://extgit.vtt.fi/gaurang.sharma/fl_with_pets
(downloaded 2026-10-22 as the `main` archive; read but **not vendored** into this repo).

Page numbers below refer to the PDF page footer ("n/14").

## 1. What the paper does

| Item | Paper says | Page |
|---|---|---|
| Task | Predict major CVD event within 4 years after cut-off 31 Dec 2020 | p.3 |
| Endpoint | ICD-10 I21 (MI), I22 (subsequent MI), I50 (heart failure) | p.3 |
| Source | Socialstyrelsen: National Patient Register, Prescribed Drug Register, Municipal Health Care register; Jan 2009 – Nov 2024 | p.3 |
| Cohort | 660,427 participants; "42,207" CVD cases; 618,394 non-CVD | p.3–4 |
| Predictors | "10 predictor variables": diabetes E10–E14, dyslipidemia E78, age, gender, ATC A10, "ATC_09" (RAAS), ATC C10 | p.4 |
| Sites (Table 1) | Östergötland 99,148 (6,518 cases); Södermanland 68,476 (4,575); Stockholm 418,000 (26,046); Uppsala 74,803 (4,894) | p.4 |
| Split | cML: 10-fold CV. FL: per-site 80 % train / 20 % validation | p.4 |
| LR learner | scikit-learn `LogisticRegression`, liblinear, defaults; 11 params | p.4 |
| NN learner | 10 → 5, ReLU, LayerNorm, → 1 logit; Xavier-uniform, zero bias; "66 params" | p.4 |
| FL | Horizontal, cross-silo, client–server, FedAvg on parameter deltas | p.4 |
| Training | 250 rounds × 20 local epochs, lr 0.01, batch 20,000 (Stockholm 100,000) | p.6 |
| DP | NVFLARE `SVTPrivacy` client-side filter ("local DP model"); λρ = 2γ/ε; threshold = τ + Lap(λρ) | p.4–5 |
| DP params (NN) | fraction 0.9, ε = 5, NoiseVar 2.5, γ = 0.1, τ = 5e-4 | p.7 |
| DP params (LR) | fraction 0.99, ε = 1e4, NoiseVar 1e2, γ = 1e-3, τ = 1e-8 | p.7 |
| HE | CKKS (TenSEAL via NVFLARE), poly degree 8192, coeff modulus [60,40,40], scale 2^40; server sums ciphertexts, multiplies by plaintext 1/Σw | p.5 |
| Infra | NVFLARE, mTLS provisioning; server + 2 clients on a 32-thread VM, Uppsala on GCP e2-medium, Stockholm on Azure B2als v2 | p.6 |
| Runtime (NN) | FedAvg 37,771 s; DP 62,721 s; HE 63,713 s | p.7 |
| Runtime (LR) | FedAvg 1,181 s; DP 1,154 s; HE 1,117 s; cML 2.52 s (LR) / 7.13 s (NN) | p.7 |
| HE cost | LR: enc/dec ≈ 0.005 s, ciphertext 1.8 KB. NN: enc 0.013 s, dec 0.007 s, ≈ 5.4 MB | p.9 |
| Evaluation | Table 2: mean ± std of global model on each site's local validation set (cross-site) | p.9, p.11 |

### Table 2 (p.11), mean ± std

| Method | Learner | AUC | Sensitivity | Specificity |
|---|---|---|---|---|
| cML | NN | 0.672 ± 0.030 | 0.166 ± 0.029 | 0.909 ± 0.015 |
| cML | LR | 0.670 ± 0.004 | 0.205 ± 0.006 | 0.899 ± 0.001 |
| FedAvg | NN | 0.680 ± 0.012 | 0.184 ± 0.034 | 0.897 ± 0.054 |
| FedAvg | LR | 0.663 ± 0.009 | 0.204 ± 0.045 | 0.892 ± 0.025 |
| FedAvg_DP | NN | 0.657 ± 0.018 | 0.079 ± 0.024 | 0.896 ± 0.058 |
| FedAvg_DP | LR | 0.623 ± 0.028 | 0.018 ± 0.071 | 0.988 ± 0.045 |
| FedAvg_HE | NN | 0.686 ± 0.011 | 0.190 ± 0.045 | 0.901 ± 0.006 |
| FedAvg_HE | LR | 0.664 ± 0.010 | 0.205 ± 0.045 | 0.893 ± 0.026 |

The brief's copy of Table 2, runtimes, HE sizes and CKKS parameters matches the PDF.

## 2. Discrepancies

### 2a. Between the brief (master prompt) and the PDF
1. **Case count.** The brief and the paper text (p.3) both say 42,207 cases, but Table 1 (p.4) sums to
   **42,033** cases. 618,394 + 42,033 = 660,427, which matches the stated cohort; 618,394 + 42,207 = 660,601 does not.
   So 42,207 is internally inconsistent in the paper. True prevalence from Table 1 is 6.36 %.
2. **"Default 0.5 threshold".** The brief says low sensitivity is due to a 0.5 threshold. **The PDF does not state
   the threshold.** The public code (`SEH_NN_learner.py::local_valid`) picks the **Youden-J-optimal threshold** for
   the NN and (`linear_learner_batch.py`) the **macro-F1-optimal threshold over 0.01–0.99** for LR, *on the same
   validation set the metrics are reported on* (optimistic, in-sample threshold). For the NN, sens 0.18 / spec 0.90
   at AUC 0.68 is not what a Youden optimum usually gives (J ≈ 0.08, where AUC 0.68 typically admits J ≈ 0.25+).
   The exact provenance of Table 2's operating points cannot be determined from the paper or code. We test both
   readings.
3. **Predictors.** The brief lists 7 predictor groups as "10 predictors". So does the paper; the split into 10 columns is
   not given (diabetes may be split by code). The paper writes "ATC_09"; RAAS agents are ATC **C09**.
4. **NN size.** 10→5 (55) + LayerNorm(5) (10) + 5→1 (6) = **71** trainable params, not 66. 66 would correspond to
   9 inputs. The code instantiates `SimpleMLP(input_dim=10)`.
5. **Optimiser and learners.** The brief says only "lr 0.01". The code uses **AdamW (weight_decay 1e-2)** for the NN, and
   for FL-LR a scikit-learn liblinear `LogisticRegression(max_iter=20)` warm-started from the global params,
   with **MinMaxScaler**. A `PTFedProxLoss` hook exists (mu = 0 by default).
6. **Batch sizes.** Not in the brief: 20,000 for three sites, 100,000 for Stockholm (p.6).
7. **"NN with 10-5-1 and LayerNorm (66 params)"**: see item 4.

### 2b. Between the PDF and the public code
1. **DP parameters differ.** Repo NN job: ε = 0.5, noise_var = 1, γ = 0.1, τ = 0.01 (paper: ε = 5, 2.5, 0.1, 5e-4).
   Repo LR job: ε = 1000 (paper: 1e4).
2. **`noise_var` is not a variance.** In `svt_privacy.py` the Laplace scale is `2γ / noise_var`, so a larger
   "NoiseVar" means *less* noise. Paper p.5 describes it as controlling the "variance".
3. **No privacy accounting.** ε applies to a single SVT release per round per client. Nothing composes it over
   250 rounds × 4 clients, so the paper gives no end-to-end (ε, δ) guarantee. The parameter perturbation is also
   clipped to ±γ *after* noise, which is post-processing (fine), but the sensitivity analysis behind λ is not
   given for model deltas.
4. The code also computes AUPRC and Brier for LR, but the paper does not report them.

## 3. Weaknesses we target (each is a hypothesis to test, not a promised win)
- Modest AUC (~0.67) with a low operating-point sensitivity (~0.2) at 6.4 % prevalence.
- No class-imbalance handling, no calibration reporting, and a threshold chosen in-sample.
- No non-IID analysis, no drift-aware FL (FedProx/SCAFFOLD/FedAdam/FedBN), no personalisation.
- DP without a formal accountant; DP and HE are evaluated separately (HE+DP left as future work, p.11).
- No fairness or explainability analysis, no significance tests, and a single (non-public) dataset.

## 4. Our reproduction target (public data, NOT comparable to the paper's numbers)
The Swedish registry data is access-controlled, so we cannot use it. The fair comparison is to **re-implement the paper's
pipeline** (cML LR/NN, FedAvg, SVT-DP with the paper's parameters, CKKS-HE with the paper's parameters) and run it
on the **same public data and splits** as our improved methods.

| Dataset | Role | n | Sites | Prevalence | Notes |
|---|---|---|---|---|---|
| UCI Heart Disease (CC BY 4.0) | Natural federation | 920 | Cleveland 303, Hungarian 294, Switzerland 123, VA 200 | 0.46 / 0.36 / 0.94 / 0.75 | Real site shift; heavy missingness at 3 sites |
| Cardiovascular Disease 70k (Kaggle) | Scale + simulated non-IID | 68,608 after cleaning | 4–8 simulated (Dirichlet α ∈ {0.1, 0.5, 1, ∞}) | 0.495 | Also a 6.4 %-prevalence subsample to mirror the paper's imbalance |

Feature policy for UCI: features missing in >50 % of rows at ≥2 sites (`slope`, `ca`, `thal`) are dropped from the
main analysis (ablation keeps them with missingness indicators). `chol` (100 % missing at Switzerland) is kept with
a missingness indicator and train-fold-only imputation.

Reporting rule: every table that shows the paper's Table 2 next to ours carries the label
**"different dataset — not directly comparable"**.
