"""Discrimination, calibration and operating-point metrics, plus threshold selection."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, roc_auc_score, roc_curve


def ece(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    """Expected calibration error with equal-width bins."""
    bins = np.minimum((p * n_bins).astype(int), n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = bins == b
        if m.any():
            total += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(total)


def operating_point(y: np.ndarray, p: np.ndarray, thr: float) -> dict[str, float]:
    pred = p >= thr
    tp = int(np.sum(pred & (y == 1)))
    fp = int(np.sum(pred & (y == 0)))
    fn = int(np.sum(~pred & (y == 1)))
    tn = int(np.sum(~pred & (y == 0)))
    div = lambda a, b: a / b if b else float("nan")  # noqa: E731
    sens, ppv = div(tp, tp + fn), div(tp, tp + fp)
    return {
        "threshold": float(thr), "sensitivity": sens, "specificity": div(tn, tn + fp),
        "ppv": ppv, "npv": div(tn, tn + fn),
        "f1": div(2 * tp, 2 * tp + fp + fn),
    }


def threshold_youden(y: np.ndarray, p: np.ndarray) -> float:
    fpr, tpr, thr = roc_curve(y, p)
    return float(np.clip(thr[np.argmax(tpr - fpr)], 0.0, 1.0))


def threshold_macro_f1(y: np.ndarray, p: np.ndarray) -> float:
    """Grid 0.01..0.99, as in the paper's LR learner."""
    grid = np.linspace(0.01, 0.99, 99)
    scores = [f1_score(y, p >= t, average="macro", zero_division=0) for t in grid]
    return float(grid[int(np.argmax(scores))])


def threshold_for_sensitivity(y: np.ndarray, p: np.ndarray, target: float = 0.8) -> float:
    fpr, tpr, thr = roc_curve(y, p)
    ok = np.flatnonzero(tpr >= target)
    return float(np.clip(thr[ok[0]], 0.0, 1.0)) if len(ok) else 0.0


THRESHOLD_RULES = {
    "youden": threshold_youden,
    "macro_f1": threshold_macro_f1,
    "sens80": threshold_for_sensitivity,
}


def threshold_free(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    two = len(np.unique(y)) == 2
    return {
        "auroc": roc_auc_score(y, p) if two else float("nan"),
        "auprc": average_precision_score(y, p) if two else float("nan"),
        "brier": brier_score_loss(y, p),
        "ece": ece(y, p),
    }
