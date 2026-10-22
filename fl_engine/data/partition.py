"""Simulated federations for datasets without natural sites."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def dirichlet_label_partition(y: np.ndarray, n_clients: int, alpha: float, seed: int,
                              min_size: int = 20) -> list[np.ndarray]:
    """Split row indices across clients with Dirichlet(alpha) label skew.

    alpha = inf gives a stratified IID split. Smaller alpha gives stronger label skew.
    Resamples until every client has at least `min_size` rows.
    """
    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    classes = np.unique(y)
    if math.isinf(alpha):
        parts: list[list[int]] = [[] for _ in range(n_clients)]
        for c in classes:
            idx = rng.permutation(np.flatnonzero(y == c))
            for k, chunk in enumerate(np.array_split(idx, n_clients)):
                parts[k].extend(chunk.tolist())
        return [np.sort(np.array(p)) for p in parts]
    for _ in range(1000):
        parts = [[] for _ in range(n_clients)]
        for c in classes:
            idx = rng.permutation(np.flatnonzero(y == c))
            props = rng.dirichlet(np.full(n_clients, alpha))
            cuts = (np.cumsum(props)[:-1] * len(idx)).astype(int)
            for k, chunk in enumerate(np.split(idx, cuts)):
                parts[k].extend(chunk.tolist())
        if min(len(p) for p in parts) >= min_size:
            return [np.sort(np.array(p)) for p in parts]
    raise RuntimeError("could not satisfy min_size; increase alpha or decrease n_clients")


def subsample_prevalence(df: pd.DataFrame, prevalence: float, seed: int, target: str = "y") -> pd.DataFrame:
    """Keep all negatives, subsample positives so that mean(target) == prevalence."""
    neg, pos = df[df[target] == 0], df[df[target] == 1]
    n_pos = int(round(prevalence / (1 - prevalence) * len(neg)))
    if n_pos > len(pos):
        raise ValueError("not enough positives for requested prevalence")
    keep = pd.concat([neg, pos.sample(n=n_pos, random_state=seed)])
    return keep.sample(frac=1.0, random_state=seed).reset_index(drop=True)
