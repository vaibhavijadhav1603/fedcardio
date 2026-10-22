"""Phase 2: federated experiments.

Suites
  uci      : 4 real hospitals, R x 5 per-site stratified CV, paper re-implementations vs our methods
  noniid   : Cardio-70k, Dirichlet label skew alpha x algorithm, K = 4
  clients  : Cardio-70k, number of clients and client dropout
  privacy  : Cardio-70k, DP-SGD epsilon sweep (privacy-utility curve) + paper SVT + HE/SecAgg cost
  imbalance: Cardio-70k at 6.4 % prevalence, loss variants (+ post-hoc thresholds / calibration)

Example: python -m experiments.run_federated --suite uci --repeats 3 --jobs 3
"""
from __future__ import annotations

import argparse
import math
import time
from dataclasses import asdict

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, train_test_split

from fl_engine.data.federated import fit_federated
from fl_engine.data.partition import dirichlet_label_partition
from fl_engine.data.preprocess import SPECS, Preprocessor
from fl_engine.eval.metrics import THRESHOLD_RULES, operating_point, threshold_free
from fl_engine.models.zoo import fit_paper_lr, fit_paper_nn
from fl_engine.sim import Client, FLConfig, run_federated, run_local_only

from .common import RESULTS, load_dataset, record

PAPER = dict(rounds=50, local_epochs=20, lr=0.01, batch_size=20000)  # paper: 250 x 20, lr .01, batch 20k

UCI_CONFIGS: dict[str, dict] = {
    "cML-LR (paper)": {"central": "lr"},
    "cML-NN (paper)": {"central": "nn"},
    "Local-only NN": {"local_only": True, "model": "paper_nn", **PAPER},
    "FedAvg-LR (paper)": {"model": "lr", **PAPER},
    "FedAvg-NN (paper)": {"model": "paper_nn", **PAPER},
    "FedAvg_DP-SVT-LR (paper)": {"model": "lr", "privacy": "svt", **PAPER},
    "FedAvg_DP-SVT-NN (paper)": {"model": "paper_nn", "privacy": "svt", **PAPER},
    "FedAvg_HE-LR (paper)": {"model": "lr", "privacy": "he", **PAPER},
    "FedAvg_HE-NN (paper)": {"model": "paper_nn", "privacy": "he", **PAPER},
    "FedAvg_HE-NN per-tensor": {"model": "paper_nn", "privacy": "he", "he_packed": False, **PAPER},
    "FedProx-NN mu=0.01": {"model": "paper_nn", "algorithm": "fedprox", "prox_mu": 0.01, **PAPER},
    "FedProx-NN mu=0.1": {"model": "paper_nn", "algorithm": "fedprox", "prox_mu": 0.1, **PAPER},
    "SCAFFOLD-NN": {"model": "paper_nn", "algorithm": "scaffold", "scaffold_lr": 0.1, **PAPER},
    "FedAdam-NN": {"model": "paper_nn", "algorithm": "fedadam", "server_lr": 0.05, **PAPER},
    "FedBN-NN": {"model": "paper_nn", "algorithm": "fedbn", **PAPER},
    "FedAvg-NN + fine-tune": {"model": "paper_nn", "finetune_epochs": 50, **PAPER},
    "FedAvg-NN class-weighted": {"model": "paper_nn", "class_weight": True, **PAPER},
    "FedAvg-LR class-weighted": {"model": "lr", "class_weight": True, **PAPER},
    "FedAvg-MLP 16x2": {"model": "mlp", **PAPER},
    "FedProx-LR mu=0.01": {"model": "lr", "algorithm": "fedprox", "prox_mu": 0.01, **PAPER},
    "SecAgg-NN": {"model": "paper_nn", "privacy": "secagg", **PAPER},
    **{f"DP-SGD-LR eps={e:g}": {"model": "lr", "privacy": "dpsgd", "dp_epsilon": e, "rounds": 50,
                                "local_epochs": 1, "dp_sample_rate": 0.2, "dp_lr": 0.5} for e in (1, 3, 8)},
    "DP-SGD-NN eps=3": {"model": "paper_nn", "privacy": "dpsgd", "dp_epsilon": 3, "rounds": 50,
                        "local_epochs": 1, "dp_sample_rate": 0.2, "dp_lr": 0.5},
    "DP-SGD+HE-LR eps=3": {"model": "lr", "privacy": "dpsgd+he", "dp_epsilon": 3, "rounds": 50,
                           "local_epochs": 1, "dp_sample_rate": 0.2, "dp_lr": 0.5},
    "DP-SGD+SecAgg-LR eps=3": {"model": "lr", "privacy": "dpsgd+secagg", "dp_epsilon": 3, "rounds": 50,
                               "local_epochs": 1, "dp_sample_rate": 0.2, "dp_lr": 0.5},
}

CARDIO_FL = dict(model="paper_nn", rounds=30, local_epochs=2, lr=0.01, batch_size=1024, eval_every=5)
CARDIO_ALGOS = {
    "FedAvg": {}, "FedProx mu=0.1": {"algorithm": "fedprox", "prox_mu": 0.1},
    "SCAFFOLD": {"algorithm": "scaffold", "scaffold_lr": 0.05}, "FedAdam": {"algorithm": "fedadam"},
    "FedBN": {"algorithm": "fedbn"},
}


# ------------------------------------------------------------------ evaluation
def platt(p_val, y_val, p_test):
    lo = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))  # noqa: E731
    if len(np.unique(y_val)) < 2:
        return p_test
    m = LogisticRegression(C=1e4).fit(lo(p_val).reshape(-1, 1), y_val)
    return m.predict_proba(lo(p_test).reshape(-1, 1))[:, 1]


def evaluate(meta: dict, sites: list[str], pred_val: dict, y_val: dict, pred_te: dict, y_te: dict):
    """Pooled test metrics under several threshold policies, Platt-calibrated Brier/ECE, per-site metrics.
    The pooled validation scores stand in for a federated ROC computed from per-site score histograms."""
    pv, yv = np.concatenate([pred_val[s] for s in sites]), np.concatenate([y_val[s] for s in sites])
    pt, yt = np.concatenate([pred_te[s] for s in sites]), np.concatenate([y_te[s] for s in sites])
    tf = threshold_free(yt, pt)
    cal = threshold_free(yt, platt(pv, yv, pt))
    site_aucs = [threshold_free(y_te[s], pred_te[s])["auroc"] for s in sites]
    base = {**meta, **tf, "brier_platt": cal["brier"], "ece_platt": cal["ece"],
            "site_mean_auroc": float(np.nanmean(site_aucs)), "worst_site_auroc": float(np.nanmin(site_aucs)),
            "n_test": len(yt), "n_train": meta.get("n_train", 0)}
    rows = []
    policies = {"val_youden": THRESHOLD_RULES["youden"](yv, pv), "val_sens80": THRESHOLD_RULES["sens80"](yv, pv),
                "fixed_0.5": 0.5, "insample_youden": THRESHOLD_RULES["youden"](yt, pt),
                "insample_macro_f1": THRESHOLD_RULES["macro_f1"](yt, pt)}
    for pol, thr in policies.items():
        rows.append({**base, "policy": pol, **operating_point(yt, pt, thr)})
    site_rows = []
    for s in sites:
        site_rows.append({**meta, "site": s, "n": len(y_te[s]), "prevalence": float(np.mean(y_te[s])),
                          **threshold_free(y_te[s], pred_te[s]),
                          **operating_point(y_te[s], pred_te[s], policies["val_youden"])})
    return rows, site_rows


def train_and_eval(name: str, spec_cfg: dict, site_data: dict, spec_key: str, meta: dict):
    """site_data: {site: (train_df, val_df, test_df)}"""
    import torch
    torch.set_num_threads(1)
    sites = list(site_data)
    seed = meta["seed"]
    is_lr = spec_cfg.get("model") == "lr" or spec_cfg.get("central") == "lr"
    scaler = "minmax" if is_lr else "standard"
    t0 = time.perf_counter()
    extra = {}
    if "central" in spec_cfg:
        tr = pd.concat([site_data[s][0] for s in sites])
        pp = Preprocessor(SPECS[spec_key], scaler=scaler).fit(tr)
        va = pd.concat([site_data[s][1] for s in sites])
        fit = fit_paper_lr if spec_cfg["central"] == "lr" else fit_paper_nn
        predict, _ = fit(pp.transform(tr), tr.y.to_numpy(), pp.transform(va), va.y.to_numpy(), seed, 0,
                         meta.get("paper_epochs_key", "uci"))
        pv = {s: predict(pp.transform(site_data[s][1])) for s in sites}
        pt = {s: predict(pp.transform(site_data[s][2])) for s in sites}
        extra = {"bytes_up": 0, "bytes_down": 0, "rounds": 0}
    else:
        pp = fit_federated([site_data[s][0] for s in sites], SPECS[spec_key], scaler=scaler)
        clients = [Client(s, pp.transform(site_data[s][0]), site_data[s][0].y.to_numpy().astype(np.float32),
                          pp.transform(site_data[s][1]), site_data[s][1].y.to_numpy().astype(np.float32))
                   for s in sites]
        kw = {k: v for k, v in spec_cfg.items() if k != "local_only"}
        cfg = FLConfig(**kw, seed=seed)
        Xm = np.vstack([c.X_val for c in clients])
        ym = np.concatenate([c.y_val for c in clients])
        res = run_local_only(clients, cfg) if spec_cfg.get("local_only") else run_federated(clients, cfg, Xm, ym)
        pv = {c.name: res.predict(c.name, c.X_val) for c in clients}
        pt = {s: res.predict(s, pp.transform(site_data[s][2])) for s in sites}
        extra = {"bytes_up": res.bytes_up, "bytes_down": res.bytes_down, "rounds": cfg.rounds,
                 "epsilon": res.epsilon, "he_encrypt_s": (res.he or {}).get("encrypt_s"),
                 "he_decrypt_s": (res.he or {}).get("decrypt_s"),
                 "he_max_abs_error": (res.he or {}).get("max_abs_error"),
                 "history": res.history if meta.get("keep_history") else None}
    wall = time.perf_counter() - t0
    y_val = {s: site_data[s][1].y.to_numpy() for s in sites}
    y_te = {s: site_data[s][2].y.to_numpy() for s in sites}
    hist = extra.pop("history", None)
    m = {**meta, "method": name, "paper_reimpl": "(paper)" in name, "wall_seconds": wall,
         "n_train": sum(len(site_data[s][0]) for s in sites), **extra}
    rows, site_rows = evaluate(m, sites, pv, y_val, pt, y_te)
    hist_rows = [{**meta, "method": name, **h} for h in (hist or [])]
    return rows, site_rows, hist_rows


# ------------------------------------------------------------------ data splits
def uci_splits(df: pd.DataFrame, repeats: int, folds: int = 5):
    for r in range(repeats):
        per_site = {s: list(StratifiedKFold(folds, shuffle=True, random_state=42 + r).split(g, g.y))
                    for s, g in df.groupby("site")}
        for f in range(folds):
            data = {}
            for s, g in df.groupby("site"):
                tr_idx, te_idx = per_site[s][f]
                train, test = g.iloc[tr_idx], g.iloc[te_idx]
                itr, iva = train_test_split(train, test_size=0.2, stratify=train.y, random_state=1000 * r + f)
                data[s] = (itr, iva, test)
            yield {"repeat": r, "fold": f, "seed": 1000 * r + f}, data


def dirichlet_sites(df: pd.DataFrame, k: int, alpha: float, seed: int):
    parts = dirichlet_label_partition(df.y.to_numpy(), k, alpha, seed, min_size=200)
    data = {}
    for i, idx in enumerate(parts):
        g = df.iloc[idx]
        strat = g.y if g.y.value_counts().min() >= 5 else None
        tr, te = train_test_split(g, test_size=0.2, stratify=strat, random_state=seed)
        strat2 = tr.y if tr.y.value_counts().min() >= 5 else None
        itr, iva = train_test_split(tr, test_size=0.125, stratify=strat2, random_state=seed)
        data[f"client{i}"] = (itr, iva, te)
    return data


def jobs_for(suite: str, repeats: int):
    if suite == "uci":
        df, spec_key = load_dataset("uci")
        for meta, data in uci_splits(df, repeats):
            for name, c in UCI_CONFIGS.items():
                yield name, c, data, spec_key, {**meta, "suite": suite, "dataset": "uci",
                                                "keep_history": meta["repeat"] == 0 and meta["fold"] == 0}
        return
    ds = "cardio_lowprev" if suite == "imbalance" else "cardio"
    df, spec_key = load_dataset(ds)
    for seed in range(repeats):
        base = {"suite": suite, "dataset": ds, "repeat": seed, "fold": 0, "seed": seed, "paper_epochs_key": ds}
        if suite == "noniid":
            for alpha in (0.1, 0.5, 1.0, math.inf):
                data = dirichlet_sites(df, 4, alpha, seed)
                for name, a in CARDIO_ALGOS.items():
                    yield name, {**CARDIO_FL, **a}, data, spec_key, {**base, "alpha": alpha, "n_clients": 4,
                                                                     "keep_history": seed == 0}
                yield "cML-NN (paper)", {"central": "nn"}, data, spec_key, {**base, "alpha": alpha, "n_clients": 4}
        elif suite == "clients":
            for k in (2, 4, 8):
                data = dirichlet_sites(df, k, 0.5, seed)
                yield "FedAvg", CARDIO_FL, data, spec_key, {**base, "alpha": 0.5, "n_clients": k, "dropout": 0.0}
                if k == 8:
                    for p in (0.3, 0.5):
                        yield "FedAvg", {**CARDIO_FL, "dropout_prob": p}, data, spec_key, \
                            {**base, "alpha": 0.5, "n_clients": k, "dropout": p}
        elif suite == "privacy":
            data = dirichlet_sites(df, 4, 0.5, seed)
            dp = dict(model="paper_nn", privacy="dpsgd", rounds=20, local_epochs=1, dp_sample_rate=0.01,
                      dp_lr=0.5, dp_clip=1.0, eval_every=5)
            for e in (0.5, 1.0, 2.0, 4.0, 8.0, math.inf):
                yield f"DP-SGD eps={e:g}", {**dp, "dp_epsilon": e}, data, spec_key, {**base, "alpha": 0.5, "eps_target": e}
            yield "FedAvg (no DP)", CARDIO_FL, data, spec_key, {**base, "alpha": 0.5, "eps_target": math.inf}
            yield "FedAvg_DP-SVT (paper)", {**CARDIO_FL, "privacy": "svt"}, data, spec_key, {**base, "alpha": 0.5}
            yield "FedAvg_HE (paper)", {**CARDIO_FL, "privacy": "he"}, data, spec_key, {**base, "alpha": 0.5}
            yield "FedAvg_HE per-tensor", {**CARDIO_FL, "privacy": "he", "he_packed": False}, data, spec_key, \
                {**base, "alpha": 0.5}
            yield "SecAgg", {**CARDIO_FL, "privacy": "secagg"}, data, spec_key, {**base, "alpha": 0.5}
        elif suite == "imbalance":
            data = dirichlet_sites(df, 4, 0.5, seed)
            for name, extra in {"FedAvg BCE": {}, "FedAvg class-weighted": {"class_weight": True},
                                "FedAvg focal": {"loss": "focal"},
                                "FedAvg-LR (paper)": {"model": "lr"}}.items():
                yield name, {**CARDIO_FL, **extra}, data, spec_key, {**base, "alpha": 0.5}
            yield "cML-LR (paper)", {"central": "lr"}, data, spec_key, {**base, "alpha": 0.5}
            yield "cML-NN (paper)", {"central": "nn"}, data, spec_key, {**base, "alpha": 0.5}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=["uci", "noniid", "clients", "privacy", "imbalance"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    t0 = time.perf_counter()
    out = Parallel(n_jobs=a.jobs, verbose=5)(delayed(train_and_eval)(*j) for j in jobs_for(a.suite, a.repeats))
    rows = [r for o in out for r in o[0]]
    site_rows = [r for o in out for r in o[1]]
    hist = [r for o in out for r in o[2]]
    stem = RESULTS / f"p2_{a.suite}"
    outputs = []
    for suffix, data in (("folds", rows), ("persite", site_rows), ("history", hist)):
        if data:
            p = stem.with_name(f"{stem.name}_{suffix}.csv")
            pd.DataFrame(data).drop(columns=["keep_history"], errors="ignore").to_csv(p, index=False)
            outputs.append(p)
    record(outputs, {**vars(a), "wall_seconds": round(time.perf_counter() - t0, 1),
                     "uci_configs": list(UCI_CONFIGS) if a.suite == "uci" else None,
                     "cardio_fl": CARDIO_FL, "paper_fl": PAPER,
                     "fl_defaults": asdict(FLConfig())})
    print(f"wrote {[str(o) for o in outputs]} in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()
