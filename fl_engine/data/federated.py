"""Federated fitting of the shared preprocessing schema.

Sites never share rows; they share only aggregate statistics (counts, sums, sums of squares,
min/max, category counts), which could themselves go through SecAgg. Two rounds:
  1. per-site counts/sums of observed numerics + category counts -> global means and modes
  2. per-site sums/sumsq (or min/max) of the imputed numerics -> global location/scale
Numeric imputation uses the pooled **mean** (medians are not decomposable), a documented
difference from the centralised Preprocessor, which uses medians.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from .preprocess import FeatureSpec, Preprocessor


def site_stats_round1(df: pd.DataFrame, spec: FeatureSpec) -> dict:
    num = df[list(spec.numeric)]
    return {
        "n_obs": num.notna().sum().to_numpy(float),
        "sum": num.sum(skipna=True).to_numpy(float),
        "cats": {c: Counter(df[c].dropna().tolist()) for c in (*spec.binary, *spec.categorical)},
    }


def fit_federated(site_dfs: list[pd.DataFrame], spec: FeatureSpec, scaler: str = "standard") -> Preprocessor:
    r1 = [site_stats_round1(d, spec) for d in site_dfs]
    n_obs = np.sum([s["n_obs"] for s in r1], axis=0)
    means = np.divide(np.sum([s["sum"] for s in r1], axis=0), n_obs, out=np.zeros_like(n_obs), where=n_obs > 0)
    modes = {}
    for c in (*spec.binary, *spec.categorical):
        tot = sum((s["cats"][c] for s in r1), Counter())
        modes[c] = tot.most_common(1)[0][0] if tot else 0

    pp = Preprocessor(spec, scaler=scaler)
    pp.medians_ = pd.Series(means, index=list(spec.numeric))
    pp.modes_ = modes
    imputed = [pp._numeric(d) for d in site_dfs]
    if scaler == "standard":
        n = sum(len(a) for a in imputed)
        s1 = np.sum([a.sum(0) for a in imputed], axis=0)
        s2 = np.sum([(a ** 2).sum(0) for a in imputed], axis=0)
        loc = s1 / n
        scale = np.sqrt(np.maximum(s2 / n - loc ** 2, 0))  # ddof=0, same as Preprocessor
    else:
        loc = np.min([a.min(0) for a in imputed], axis=0)
        scale = np.max([a.max(0) for a in imputed], axis=0) - loc
    pp.loc_, pp.scale_ = loc, np.where(scale > 1e-12, scale, 1.0)
    pp.feature_names_ = Preprocessor(spec).fit(site_dfs[0]).feature_names_
    return pp
