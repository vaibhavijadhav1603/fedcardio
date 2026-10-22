"""Statistics for repeated cross-validation and paired model comparison."""
from __future__ import annotations

import numpy as np
from scipy import stats


def corrected_ci(x: np.ndarray, test_train_ratio: float, level: float = 0.95) -> tuple[float, float, float]:
    """Mean and CI with the Nadeau & Bengio (2003) corrected resampled-t variance.

    Repeated-CV folds share training data, so the naive variance s^2/k is too small;
    the correction uses (1/k + n_test/n_train) * s^2.
    """
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    k = len(x)
    m = float(x.mean())
    if k < 2:
        return m, float("nan"), float("nan")
    se = np.sqrt((1 / k + test_train_ratio) * x.var(ddof=1))
    h = stats.t.ppf(0.5 + level / 2, k - 1) * se
    return m, m - h, m + h


def corrected_paired_ttest(a: np.ndarray, b: np.ndarray, test_train_ratio: float) -> tuple[float, float]:
    """Two-sided corrected resampled t-test on paired per-fold scores. Returns (mean diff, p)."""
    d = np.asarray(a, float) - np.asarray(b, float)
    d = d[~np.isnan(d)]
    k = len(d)
    var = d.var(ddof=1)
    if var == 0:
        return float(d.mean()), 1.0 if d.mean() == 0 else 0.0
    t = d.mean() / np.sqrt((1 / k + test_train_ratio) * var)
    return float(d.mean()), float(2 * stats.t.sf(abs(t), k - 1))


def holm(pvals: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (len(p) - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj.tolist()


def delong_test(y: np.ndarray, p1: np.ndarray, p2: np.ndarray) -> tuple[float, float, float]:
    """DeLong (1988) test for two correlated AUCs (fast midrank implementation, Sun & Xu 2014).
    Returns (auc1, auc2, two-sided p)."""
    y = np.asarray(y)
    pos, neg = y == 1, y == 0
    m, n = pos.sum(), neg.sum()
    preds = np.vstack([p1, p2])

    def midrank(x):
        order = np.argsort(x)
        xs = x[order]
        ranks = np.empty(len(x))
        i = 0
        while i < len(x):
            j = i
            while j < len(x) and xs[j] == xs[i]:
                j += 1
            ranks[i:j] = 0.5 * (i + j - 1) + 1
            i = j
        out = np.empty(len(x))
        out[order] = ranks
        return out

    tx = np.array([midrank(p[pos]) for p in preds])
    ty = np.array([midrank(p[neg]) for p in preds])
    tz = np.array([midrank(np.concatenate([p[pos], p[neg]])) for p in preds])
    aucs = tz[:, :m].sum(1) / (m * n) - (m + 1) / (2 * n)
    v01 = (tz[:, :m] - tx) / n
    v10 = 1 - (tz[:, m:] - ty) / m
    s = np.cov(v01) / m + np.cov(v10) / n
    var = s[0, 0] + s[1, 1] - 2 * s[0, 1]
    z = (aucs[0] - aucs[1]) / np.sqrt(var) if var > 0 else 0.0
    return float(aucs[0]), float(aucs[1]), float(2 * stats.norm.sf(abs(z)))
