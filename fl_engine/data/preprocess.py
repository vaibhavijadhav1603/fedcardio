"""Leakage-free preprocessing: every statistic is fitted on training rows only.

A `FeatureSpec` fixes the schema per dataset, so every site and fold produces identical
columns in an identical order, which federated training needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureSpec:
    numeric: tuple[str, ...]
    binary: tuple[str, ...] = ()
    categorical: dict[str, tuple] = field(default_factory=dict)
    missing_indicators: tuple[str, ...] = ()


UCI_MAIN = FeatureSpec(
    numeric=("age", "trestbps", "chol", "thalach", "oldpeak"),
    binary=("sex", "fbs", "exang"),
    categorical={"cp": (1.0, 2.0, 3.0, 4.0), "restecg": (0.0, 1.0, 2.0)},
    missing_indicators=("trestbps", "chol", "fbs", "thalach"),
)

# Ablation: also keep the heavily-missing angiographic/ECG features.
UCI_FULL = FeatureSpec(
    numeric=UCI_MAIN.numeric + ("ca",),
    binary=UCI_MAIN.binary,
    categorical={**UCI_MAIN.categorical, "slope": (1.0, 2.0, 3.0), "thal": (3.0, 6.0, 7.0)},
    missing_indicators=UCI_MAIN.missing_indicators + ("ca", "slope", "thal"),
)

CARDIO = FeatureSpec(
    numeric=("age", "height", "weight", "bmi", "ap_hi", "ap_lo"),
    binary=("sex", "smoke", "alco", "active"),
    categorical={"cholesterol": (1, 2, 3), "gluc": (1, 2, 3)},
)

SPECS = {"uci_main": UCI_MAIN, "uci_full": UCI_FULL, "cardio": CARDIO}


class Preprocessor:
    """Median/mode imputation, missingness indicators, fixed one-hot, scaling.

    scaler: "standard" (default) or "minmax" (what the paper's LR learner used).
    """

    def __init__(self, spec: FeatureSpec, scaler: str = "standard"):
        if scaler not in ("standard", "minmax"):
            raise ValueError(scaler)
        self.spec, self.scaler = spec, scaler

    def fit(self, df: pd.DataFrame) -> Preprocessor:
        s = self.spec
        self.medians_ = df[list(s.numeric)].median()
        self.modes_ = {c: df[c].mode(dropna=True).iloc[0] if df[c].notna().any() else 0
                       for c in (*s.binary, *s.categorical)}
        # a column entirely missing in the training rows (e.g. chol at Switzerland) falls back to 0
        self.medians_ = self.medians_.fillna(0.0)
        num = self._numeric(df)
        if self.scaler == "standard":
            self.loc_, self.scale_ = num.mean(0), num.std(0)
        else:
            self.loc_, self.scale_ = num.min(0), num.max(0) - num.min(0)
        self.scale_ = np.where(self.scale_ > 1e-12, self.scale_, 1.0)
        self.feature_names_ = (
            list(s.numeric) + list(s.binary)
            + [f"{c}={v:g}" for c, vals in s.categorical.items() for v in vals]
            + [f"{c}_missing" for c in s.missing_indicators]
        )
        return self

    def _numeric(self, df: pd.DataFrame) -> np.ndarray:
        return df[list(self.spec.numeric)].fillna(self.medians_).to_numpy(float)

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        s = self.spec
        num = (self._numeric(df) - self.loc_) / self.scale_
        parts = [num]
        if s.binary:
            parts.append(np.column_stack([df[c].fillna(self.modes_[c]).to_numpy(float) for c in s.binary]))
        for c, vals in s.categorical.items():
            col = df[c].fillna(self.modes_[c]).to_numpy()
            parts.append(np.column_stack([(col == v).astype(float) for v in vals]))
        if s.missing_indicators:
            parts.append(np.column_stack([df[c].isna().to_numpy(float) for c in s.missing_indicators]))
        return np.hstack(parts).astype(np.float32)

    def fit_transform(self, df: pd.DataFrame) -> np.ndarray:
        return self.fit(df).transform(df)
