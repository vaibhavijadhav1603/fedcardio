"""Loaders that return raw (un-imputed) dataframes with a harmonized schema.

Imputation and scaling are NOT done here: they must be fitted on training folds
only (see fl_engine.data.preprocess) to avoid leakage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .download import RAW

UCI_COLUMNS = [
    "age", "sex", "cp", "trestbps", "chol", "fbs", "restecg",
    "thalach", "exang", "oldpeak", "slope", "ca", "thal", "num",
]
UCI_SITES = {
    "cleveland": "processed.cleveland.data",
    "hungarian": "processed.hungarian.data",
    "switzerland": "processed.switzerland.data",
    "va_long_beach": "processed.va.data",
}


def load_uci_heart() -> pd.DataFrame:
    """UCI Heart Disease, one row per patient, with a `site` column.

    Target: `y = 1` if `num > 0` (any angiographic narrowing >50%), the
    standard binarisation used in the literature.
    Serum cholesterol recorded as 0 (common at Switzerland/VA) is treated as missing.
    """
    frames = []
    for site, fname in UCI_SITES.items():
        df = pd.read_csv(RAW / "uci_heart" / fname, header=None, names=UCI_COLUMNS, na_values="?")
        df["site"] = site
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["chol"] = df["chol"].replace(0, np.nan)
    df["trestbps"] = df["trestbps"].replace(0, np.nan)
    df["y"] = (df["num"] > 0).astype(int)
    return df.drop(columns=["num"])


def load_cardio70k(clean: bool = True) -> pd.DataFrame:
    """Kaggle Cardiovascular Disease dataset (70,000 records, single source).

    Age is converted from days to years; gender recoded to sex (1 = male, 0 = female).
    With `clean=True`, physiologically implausible blood pressure / anthropometrics
    are removed (rule documented in data/README.md).
    """
    df = pd.read_csv(RAW / "cardio70k" / "cardio_train.csv", sep=";")
    df = df.drop(columns=["id"])
    df["age"] = df["age"] / 365.25
    df["sex"] = (df["gender"] == 2).astype(int)
    df = df.drop(columns=["gender"])
    df = df.rename(columns={"cardio": "y"})
    if clean:
        ok = (
            df["ap_hi"].between(80, 250)
            & df["ap_lo"].between(40, 160)
            & (df["ap_hi"] > df["ap_lo"])
            & df["height"].between(120, 220)
            & df["weight"].between(30, 250)
        )
        df = df[ok].reset_index(drop=True)
    df["bmi"] = df["weight"] / (df["height"] / 100) ** 2
    return df


def summarize(df: pd.DataFrame, by: str | None = "site") -> pd.DataFrame:
    groups = df.groupby(by) if by else [("all", df)]
    rows = []
    for key, g in groups:
        miss = g.drop(columns=[c for c in ("site", "y") if c in g]).isna().mean()
        rows.append({
            "group": key, "n": len(g), "positives": int(g["y"].sum()),
            "prevalence": round(g["y"].mean(), 3),
            "max_missing_feature": miss.idxmax() if miss.max() > 0 else "-",
            "max_missing_frac": round(miss.max(), 3),
        })
    return pd.DataFrame(rows)
