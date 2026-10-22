"""Numpy-only serving of registry models (logistic regression or the paper MLP).

Returns calibrated probability, threshold decision, per-feature contributions (Shapley values in
logit space: exact for the linear model, permutation-sampled for the MLP), and an
out-of-distribution warning when inputs fall outside the training range.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

FIELD_META = {
    "age": {"label": "Age", "unit": "years", "min": 18, "max": 100, "kind": "number"},
    "sex": {"label": "Sex", "kind": "select", "options": [{"value": 1, "label": "Male"}, {"value": 0, "label": "Female"}]},
    "cp": {"label": "Chest pain type", "kind": "select", "options": [
        {"value": 1, "label": "Typical angina"}, {"value": 2, "label": "Atypical angina"},
        {"value": 3, "label": "Non-anginal pain"}, {"value": 4, "label": "Asymptomatic"}]},
    "trestbps": {"label": "Resting systolic BP", "unit": "mmHg", "min": 70, "max": 240, "kind": "number"},
    "chol": {"label": "Serum cholesterol", "unit": "mg/dL", "min": 80, "max": 650, "kind": "number"},
    "fbs": {"label": "Fasting blood sugar > 120 mg/dL", "kind": "select",
            "options": [{"value": 1, "label": "Yes"}, {"value": 0, "label": "No"}]},
    "restecg": {"label": "Resting ECG", "kind": "select", "options": [
        {"value": 0, "label": "Normal"}, {"value": 1, "label": "ST-T abnormality"}, {"value": 2, "label": "LV hypertrophy"}]},
    "thalach": {"label": "Max heart rate (exercise)", "unit": "bpm", "min": 60, "max": 220, "kind": "number"},
    "exang": {"label": "Exercise-induced angina", "kind": "select",
              "options": [{"value": 1, "label": "Yes"}, {"value": 0, "label": "No"}]},
    "oldpeak": {"label": "ST depression (exercise)", "unit": "mm", "min": -3, "max": 7, "kind": "number"},
}

PLAIN = {
    "age": "Age", "sex": "Sex (male)", "trestbps": "Resting blood pressure", "chol": "Cholesterol",
    "thalach": "Maximum heart rate", "oldpeak": "ST depression on exercise", "fbs": "High fasting blood sugar",
    "exang": "Angina on exercise", "cp=1": "Typical angina", "cp=2": "Atypical angina",
    "cp=3": "Non-anginal chest pain", "cp=4": "Asymptomatic chest pain type", "restecg=0": "Normal resting ECG",
    "restecg=1": "ST-T abnormality on ECG", "restecg=2": "LV hypertrophy on ECG",
    "trestbps_missing": "Blood pressure not recorded", "chol_missing": "Cholesterol not recorded",
    "fbs_missing": "Blood sugar not recorded", "thalach_missing": "Heart rate not recorded",
}


class ServedModel:
    def __init__(self, card: dict):
        self.card = card
        f = card["features"]
        self.numeric, self.binary = f["numeric"], f["binary"]
        self.categorical = {k: [float(x) for x in v] for k, v in f["categorical"].items()}
        self.missing = f["missing_indicators"]
        self.names = f["names"]
        pp = card["preprocessing"]
        self.impute_num = pp["impute_numeric"]
        self.impute_mode = pp["impute_mode"]
        self.loc, self.scale = np.array(pp["loc"]), np.array(pp["scale"])
        self.w = {k: np.array(v, dtype=float) for k, v in card["weights"].items()}
        self.arch = card["architecture"]
        self.bg = np.array(card["shap_background"])
        self.ood = {k: np.array(v) for k, v in card["ood"].items()}

    # -- preprocessing identical to fl_engine.data.preprocess.Preprocessor.transform
    def vectorize(self, raw: dict) -> np.ndarray:
        def val(k):
            v = raw.get(k)
            return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
        num = np.array([val(k) if val(k) is not None else self.impute_num[k] for k in self.numeric])
        parts = [(num - self.loc) / self.scale]
        parts.append(np.array([val(k) if val(k) is not None else self.impute_mode[k] for k in self.binary]))
        for k, cats in self.categorical.items():
            v = val(k) if val(k) is not None else self.impute_mode[k]
            parts.append(np.array([1.0 if v == c else 0.0 for c in cats]))
        parts.append(np.array([1.0 if val(k) is None else 0.0 for k in self.missing]))
        return np.concatenate(parts)

    def logit(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(X)
        w = self.w
        if self.arch == "logistic_regression":
            return X @ w["fc.weight"][0] + w["fc.bias"][0]
        h = X @ w["fc1.weight"].T + w["fc1.bias"]
        mu, var = h.mean(1, keepdims=True), h.var(1, keepdims=True)
        h = (h - mu) / np.sqrt(var + 1e-5) * w["ln.weight"] + w["ln.bias"]
        return np.maximum(h, 0) @ w["fc2.weight"][0] + w["fc2.bias"][0]

    def calibrated(self, z: np.ndarray) -> np.ndarray:
        c = self.card["calibration"]
        return 1 / (1 + np.exp(-(c["a"] * z + c["b"])))

    def contributions(self, x: np.ndarray) -> np.ndarray:
        if self.arch == "logistic_regression":
            return self.w["fc.weight"][0] * (x - self.bg.mean(0))
        rng = np.random.default_rng(0)
        d = len(x)
        phi = np.zeros(d)
        n_perm = 64
        for _ in range(n_perm):
            order = rng.permutation(d)
            z = self.bg[rng.integers(len(self.bg))].copy()
            prev = self.logit(z)[0]
            for j in order:
                z[j] = x[j]
                cur = self.logit(z)[0]
                phi[j] += cur - prev
                prev = cur
        return phi / n_perm

    def predict(self, raw: dict, top_k: int = 6) -> dict:
        x = self.vectorize(raw)
        z = float(self.logit(x)[0])
        p_raw = float(1 / (1 + np.exp(-z)))
        p = float(self.calibrated(np.array([z]))[0])
        thr = float(self.card["threshold"]["value"])
        phi = self.contributions(x)
        order = np.argsort(-np.abs(phi))
        contrib = [{"feature": self.names[j], "label": PLAIN.get(self.names[j], self.names[j]),
                    "value": float(phi[j]), "direction": "increases" if phi[j] > 0 else "decreases"}
                   for j in order[:top_k] if abs(phi[j]) > 1e-9]
        lo, hi = self.ood["min"], self.ood["max"]
        span = np.maximum(hi - lo, 1e-6)
        outside = [self.names[j] for j in range(len(x)) if x[j] < lo[j] - 0.25 * span[j] or x[j] > hi[j] + 0.25 * span[j]]
        missing = [k for k in (*self.numeric, *self.binary, *self.categorical) if raw.get(k) is None]
        band = "high" if p >= thr + 0.15 else "elevated" if p >= thr else "low" if p < thr - 0.15 else "borderline-low"
        return {
            "probability": p, "probability_uncalibrated": p_raw, "threshold": thr,
            "decision": "above_threshold" if p >= thr else "below_threshold", "risk_band": band,
            "near_threshold": abs(p - thr) < 0.05,
            "contributions": contrib, "baseline_probability": float(self.calibrated(self.logit(self.bg).mean(keepdims=True))[0]),
            "ood_warning": bool(outside), "ood_features": outside, "missing_inputs": missing,
            "model_id": self.card["id"], "model_version": self.card["version"],
        }


@lru_cache(maxsize=16)
def load_model(path: str) -> ServedModel:
    return ServedModel(json.loads(Path(path).read_text()))
