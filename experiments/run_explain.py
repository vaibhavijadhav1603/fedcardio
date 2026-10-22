"""Fairness + SHAP analysis on UCI, and export of the deployable model to the registry.

python -m experiments.run_explain --method "FedAvg-LR (paper)" --version 1.0.0
  -> results/p2_fairness.csv, results/p2_shap_sites.csv, models/registry/<id>/model.json

The exported model is plain JSON (weights, preprocessing statistics, threshold, Platt
calibration, OOD reference ranges), so the backend can serve it with numpy only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import torch
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, train_test_split

from fl_engine.data.federated import fit_federated
from fl_engine.data.preprocess import SPECS
from fl_engine.eval.metrics import THRESHOLD_RULES, operating_point, threshold_free
from fl_engine.explain import shapley_values
from fl_engine.sim import Client, FLConfig, run_federated

from .common import RESULTS, ROOT, git_state, load_dataset, record
from .run_federated import UCI_CONFIGS

REGISTRY = ROOT / "models" / "registry"


def train(method: str, site_frames: dict, spec_key: str, seed: int):
    cfg = UCI_CONFIGS[method]
    scaler = "minmax" if cfg.get("model") == "lr" else "standard"
    pp = fit_federated([tr for tr, _ in site_frames.values()], SPECS[spec_key], scaler=scaler)
    clients = [Client(s, pp.transform(tr), tr.y.to_numpy().astype(np.float32), pp.transform(va),
                      va.y.to_numpy().astype(np.float32)) for s, (tr, va) in site_frames.items()]
    res = run_federated(clients, FLConfig(**cfg, seed=seed))
    return pp, res, clients


def age_band(a):
    return pd.cut(a, [0, 50, 60, 200], right=False, labels=["<50", "50-59", "60+"]).astype(str)


def fairness(method: str, seed: int = 0) -> pd.DataFrame:
    """Out-of-fold predictions (per-site 5-fold) -> subgroup metrics at the val-chosen threshold."""
    df, spec_key = load_dataset("uci")
    oof = []
    per_site = {s: list(StratifiedKFold(5, shuffle=True, random_state=seed).split(g, g.y)) for s, g in df.groupby("site")}
    for f in range(5):
        frames, tests = {}, []
        for s, g in df.groupby("site"):
            tr_idx, te_idx = per_site[s][f]
            tr, va = train_test_split(g.iloc[tr_idx], test_size=0.2, stratify=g.iloc[tr_idx].y, random_state=f)
            frames[s] = (tr, va)
            tests.append(g.iloc[te_idx])
        pp, res, clients = train(method, frames, spec_key, seed + f)
        pv = np.concatenate([res.predict(c.name, c.X_val) for c in clients])
        yv = np.concatenate([c.y_val for c in clients])
        thr = THRESHOLD_RULES["youden"](yv, pv)
        for t in tests:
            oof.append(t.assign(p=res.predict(t.site.iat[0], pp.transform(t)), thr=thr))
    o = pd.concat(oof)
    o["sex_label"] = o.sex.map({1.0: "male", 0.0: "female"})
    o["age_band"] = age_band(o.age)
    rows = []
    for attr in ("sex_label", "age_band", "site"):
        for grp, g in o.groupby(attr):
            pred = (g.p >= g.thr).to_numpy()
            rows.append({"method": method, "attribute": attr.replace("_label", ""), "group": grp, "n": len(g),
                         "prevalence": g.y.mean(), **threshold_free(g.y.to_numpy(), g.p.to_numpy()),
                         "sensitivity": (pred & (g.y == 1)).sum() / max(1, (g.y == 1).sum()),
                         "specificity": (~pred & (g.y == 0)).sum() / max(1, (g.y == 0).sum()),
                         "positive_rate": pred.mean()})
    return pd.DataFrame(rows)


def export(method: str, version: str, seed: int = 0) -> tuple[dict, pd.DataFrame]:
    df, spec_key = load_dataset("uci")
    frames = {}
    for s, g in df.groupby("site"):
        tr, va = train_test_split(g, test_size=0.2, stratify=g.y, random_state=seed)
        frames[s] = (tr, va)
    pp, res, clients = train(method, frames, spec_key, seed)
    model = res.global_model
    predict = lambda X: torch.sigmoid(model(torch.as_tensor(X, dtype=torch.float32))).detach().numpy()  # noqa: E731
    Xv = np.vstack([c.X_val for c in clients])
    yv = np.concatenate([c.y_val for c in clients])
    pv = predict(Xv)
    logit = np.log(np.clip(pv, 1e-6, 1 - 1e-6) / (1 - np.clip(pv, 1e-6, 1 - 1e-6)))
    platt = LogisticRegression(C=1e4).fit(logit.reshape(-1, 1), yv)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    p_cal = 1 / (1 + np.exp(-(a * logit + b)))
    thr = THRESHOLD_RULES["youden"](yv, p_cal)
    Xtr = np.vstack([c.X for c in clients])

    # SHAP per site (same model) -> consistency of global importance across hospitals
    names = pp.feature_names_
    bg = Xtr[np.random.default_rng(seed).choice(len(Xtr), 50, replace=False)]
    shap_rows = []
    for c in clients:
        sv = shapley_values(predict_logit_fn(model), c.X[:80], bg, n_perm=30, seed=seed)
        for j, n in enumerate(names):
            shap_rows.append({"site": c.name, "feature": n, "mean_abs_shap": float(np.abs(sv[:, j]).mean())})
    shap_df = pd.DataFrame(shap_rows)
    piv = shap_df.pivot(index="feature", columns="site", values="mean_abs_shap")
    rhos = [spearmanr(piv[s1], piv[s2]).statistic for i, s1 in enumerate(piv) for s2 in list(piv)[i + 1:]]

    state = {k: v.detach().numpy().tolist() for k, v in model.state_dict().items()}
    arch = "logistic_regression" if UCI_CONFIGS[method].get("model") == "lr" else "paper_mlp"
    card = {
        "id": f"uci-{arch}-{version}", "version": version, "name": f"FedCardio {method}",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_state()["commit"], "training_method": method, "architecture": arch,
        "dataset": "UCI Heart Disease (Cleveland, Hungarian, Switzerland, VA Long Beach), federated across 4 sites",
        "target": "angiographic coronary artery disease (num > 0); NOT 4-year incident MI/HF",
        "intended_use": "Research demonstration of privacy-preserving federated learning. Not for clinical decisions.",
        "limitations": ["Research prototype; no clinical validation.", "Trained on 1980s referral cohorts (n=920).",
                        "Prevalence differs strongly by site; calibration may not transfer.",
                        "Features with heavy missingness (slope, ca, thal) excluded."],
        "features": {"spec": spec_key, "names": names, "numeric": list(SPECS[spec_key].numeric),
                     "binary": list(SPECS[spec_key].binary),
                     "categorical": {k: list(v) for k, v in SPECS[spec_key].categorical.items()},
                     "missing_indicators": list(SPECS[spec_key].missing_indicators)},
        "preprocessing": {"scaler": pp.scaler, "impute_numeric": pp.medians_.to_dict(),
                          "impute_mode": {k: float(v) for k, v in pp.modes_.items()},
                          "loc": np.asarray(pp.loc_).tolist(), "scale": np.asarray(pp.scale_).tolist()},
        "weights": state, "calibration": {"method": "platt", "a": a, "b": b},
        "threshold": {"rule": "youden_on_validation", "value": thr},
        "ood": {"min": Xtr.min(0).tolist(), "max": Xtr.max(0).tolist(), "mean": Xtr.mean(0).tolist(),
                "std": Xtr.std(0).tolist()},
        "shap_background": bg[:20].tolist(),
        "validation_metrics": {**threshold_free(yv, p_cal), **operating_point(yv, p_cal, thr)},
        "shap_site_consistency_spearman_mean": float(np.mean(rhos)),
        "privacy": {"mechanism": UCI_CONFIGS[method].get("privacy", "none"),
                    "note": "see docs/THREAT_MODEL.md"},
    }
    out_dir = REGISTRY / card["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "model.json").write_text(json.dumps(card, indent=1))
    card["sha256"] = hashlib.sha256((out_dir / "model.json").read_bytes()).hexdigest()
    return card, shap_df


def predict_logit_fn(model):
    def f(X):
        with torch.no_grad():
            return model(torch.as_tensor(X, dtype=torch.float32)).numpy()
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", default="FedAvg-LR (paper)")
    ap.add_argument("--version", default="1.0.0")
    a = ap.parse_args()
    fair = fairness(a.method)
    card, shap_df = export(a.method, a.version)
    outs = [RESULTS / "p2_fairness.csv", RESULTS / "p2_shap_sites.csv"]
    fair.to_csv(outs[0], index=False)
    shap_df.to_csv(outs[1], index=False)
    record(outs, {"script": "run_explain", **vars(a), "model_id": card["id"], "model_sha256": card["sha256"]})
    print(fair.round(3).to_string(index=False))
    print("exported", card["id"], "val metrics", {k: round(v, 3) for k, v in card["validation_metrics"].items()},
          "SHAP site consistency rho", round(card["shap_site_consistency_spearman_mean"], 3))


if __name__ == "__main__":
    main()
