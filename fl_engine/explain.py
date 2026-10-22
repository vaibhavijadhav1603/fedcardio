"""Model-agnostic Shapley values by permutation sampling (interventional, background set).

Exact for linear models in expectation; numpy-only so the backend can reuse the same logic.
Values are in the model's output units (logit when `f` returns logits).
"""
from __future__ import annotations

import numpy as np


def shapley_values(f, X: np.ndarray, background: np.ndarray, n_perm: int = 50, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n, d = X.shape
    phi = np.zeros((n, d))
    for _ in range(n_perm):
        order = rng.permutation(d)
        z = background[rng.integers(len(background), size=n)].copy()
        prev = f(z)
        for j in order:
            z[:, j] = X[:, j]
            cur = f(z)
            phi[:, j] += cur - prev
            prev = cur
    return phi / n_perm
