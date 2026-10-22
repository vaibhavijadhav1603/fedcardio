import math

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from fl_engine.data.partition import dirichlet_label_partition, subsample_prevalence
from fl_engine.data.preprocess import CARDIO, UCI_MAIN, Preprocessor
from fl_engine.eval.metrics import (
    ece, operating_point, threshold_for_sensitivity, threshold_free, threshold_macro_f1, threshold_youden,
)
from fl_engine.eval.stats import corrected_ci, corrected_paired_ttest, delong_test, holm
from fl_engine.models.nets import LogReg, PaperMLP, TunableMLP, n_params, predict_proba, train_torch


def toy_uci(n=60, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "age": rng.normal(55, 9, n), "trestbps": rng.normal(130, 15, n), "chol": rng.normal(240, 40, n),
        "thalach": rng.normal(140, 20, n), "oldpeak": rng.exponential(1, n),
        "sex": rng.integers(0, 2, n).astype(float), "fbs": rng.integers(0, 2, n).astype(float),
        "exang": rng.integers(0, 2, n).astype(float), "cp": rng.integers(1, 5, n).astype(float),
        "restecg": rng.integers(0, 3, n).astype(float), "y": rng.integers(0, 2, n),
    })
    df.loc[:9, "chol"] = np.nan
    return df


# ---------- preprocessing ----------
def test_preprocessor_schema_and_no_leakage():
    tr, te = toy_uci(seed=1), toy_uci(seed=2)
    te["age"] += 100  # a shift in test data must not change fitted statistics
    pp = Preprocessor(UCI_MAIN).fit(tr)
    before = pp.loc_.copy()
    Xte = pp.transform(te)
    assert np.allclose(pp.loc_, before)
    assert Xte.shape[1] == len(pp.feature_names_) == 5 + 3 + 4 + 3 + 4
    assert not np.isnan(Xte).any()
    Xtr = pp.transform(tr)
    assert np.allclose(Xtr[:, :5].mean(0), 0, atol=1e-5)
    assert Xtr[:10, pp.feature_names_.index("chol_missing")].tolist() == [1.0] * 10


def test_preprocessor_handles_fully_missing_column_and_minmax():
    tr = toy_uci()
    tr["chol"] = np.nan  # like Switzerland
    X = Preprocessor(UCI_MAIN, scaler="minmax").fit_transform(tr)
    assert not np.isnan(X).any()
    assert X[:, 0].min() >= 0 and X[:, 0].max() <= 1 + 1e-6
    with pytest.raises(ValueError):
        Preprocessor(UCI_MAIN, scaler="robust")


def test_cardio_spec_feature_count():
    assert len(CARDIO.numeric) + len(CARDIO.binary) + 6 == 16


# ---------- partitioning ----------
@pytest.mark.parametrize("alpha", [0.1, 0.5, 1.0, math.inf])
def test_dirichlet_partition_is_a_partition(alpha):
    y = np.random.default_rng(0).integers(0, 2, 2000)
    parts = dirichlet_label_partition(y, 5, alpha, seed=3)
    allidx = np.concatenate(parts)
    assert len(allidx) == len(y) and len(np.unique(allidx)) == len(y)
    assert min(len(p) for p in parts) >= 20


def test_dirichlet_skew_increases_as_alpha_decreases():
    y = np.random.default_rng(0).integers(0, 2, 5000)
    spread = lambda a: np.std([y[p].mean() for p in dirichlet_label_partition(y, 6, a, seed=1)])  # noqa: E731
    assert spread(0.1) > spread(1.0) > spread(math.inf)
    assert spread(math.inf) < 0.01


def test_subsample_prevalence():
    df = pd.DataFrame({"y": [0] * 900 + [1] * 500})
    out = subsample_prevalence(df, 0.1, seed=0)
    assert abs(out.y.mean() - 0.1) < 0.002 and (out.y == 0).sum() == 900
    with pytest.raises(ValueError):
        subsample_prevalence(df, 0.9, seed=0)


# ---------- models ----------
def test_paper_mlp_parameter_count():
    assert n_params(PaperMLP(10)) == 71  # paper says 66; see docs/SPEC.md
    assert n_params(PaperMLP(9)) == 66
    assert n_params(LogReg(10)) == 11


def test_training_learns_separable_data():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 4)).astype(np.float32)
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(np.float32)
    for m in (PaperMLP(4), TunableMLP(4, hidden=8, layers=1), LogReg(4)):
        train_torch(m, X, y, epochs=60, lr=0.02, batch_size=64, seed=0)
        assert roc_auc_score(y, predict_proba(m, X)) > 0.95


def test_early_stopping_and_focal_loss_run():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(200, 3)).astype(np.float32)
    y = (X[:, 0] > 0).astype(np.float32)
    m = train_torch(LogReg(3), X, y, epochs=50, lr=0.05, batch_size=32, X_val=X, y_val=y, patience=3,
                    loss="focal", pos_weight=2.0)
    assert roc_auc_score(y, predict_proba(m, X)) > 0.9


# ---------- metrics ----------
def test_operating_point_and_thresholds():
    y = np.array([0, 0, 0, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.6, 0.4, 0.8, 0.9])
    op = operating_point(y, p, 0.5)
    assert op["sensitivity"] == pytest.approx(2 / 3) and op["specificity"] == pytest.approx(2 / 3)
    assert op["ppv"] == pytest.approx(2 / 3)
    assert 0 <= threshold_youden(y, p) <= 1
    assert operating_point(y, p, threshold_for_sensitivity(y, p, 1.0))["sensitivity"] == 1.0
    assert 0.01 <= threshold_macro_f1(y, p) <= 0.99
    tf = threshold_free(y, p)
    assert tf["auroc"] == pytest.approx(roc_auc_score(y, p))
    assert math.isnan(threshold_free(np.zeros(4), np.full(4, 0.3))["auroc"])


def test_ece_perfect_and_bad_calibration():
    rng = np.random.default_rng(0)
    p = rng.uniform(size=20000)
    y = (rng.uniform(size=20000) < p).astype(int)
    assert ece(y, p) < 0.02
    assert ece(y, np.clip(p + 0.3, 0, 1)) > 0.15


# ---------- stats ----------
def test_corrected_ci_wider_than_naive():
    x = np.random.default_rng(0).normal(0.8, 0.02, 25)
    m, lo, hi = corrected_ci(x, 0.25)
    naive = 1.96 * x.std(ddof=1) / 5
    assert lo < m < hi and (hi - lo) / 2 > naive


def test_paired_ttest_and_holm():
    rng = np.random.default_rng(0)
    a = rng.normal(0.8, 0.01, 25)
    d, p = corrected_paired_ttest(a + 0.05, a, 0.25)
    assert d == pytest.approx(0.05) and p < 1e-3
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_delong_matches_sklearn_auc_and_detects_difference():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 2000)
    good = y + rng.normal(0, 0.8, 2000)
    bad = y + rng.normal(0, 3.0, 2000)
    a1, a2, p = delong_test(y, good, bad)
    assert a1 == pytest.approx(roc_auc_score(y, good)) and a2 == pytest.approx(roc_auc_score(y, bad))
    assert p < 1e-6
    assert delong_test(y, good, good)[2] == pytest.approx(1.0)
