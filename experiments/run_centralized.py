"""Phase 1: centralised baselines + paper re-implementations under repeated stratified CV.

Example:
  python -m experiments.run_centralized --dataset uci --repeats 5 --folds 5 --budget 20
Writes results/p1_<dataset>_folds.csv (and _persite.csv for UCI) and appends to results/manifest.json.
"""
from __future__ import annotations

import argparse
import os
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split

from fl_engine.data.preprocess import SPECS, Preprocessor
from fl_engine.eval.metrics import THRESHOLD_RULES, operating_point, threshold_free
from fl_engine.models.zoo import ZOO

from .common import RESULTS, load_dataset, record


def run_fold(df, spec_key, dataset, rep, fold, tr_idx, te_idx, models, budget):
    import torch
    torch.set_num_threads(1)
    seed = 1000 * rep + fold
    train, test = df.iloc[tr_idx], df.iloc[te_idx]
    strat = train["site"].astype(str) + train["y"].astype(str) if "site" in train else train["y"]
    inner_tr, inner_va = train_test_split(train, test_size=0.2, stratify=strat, random_state=seed)
    rows, site_rows = [], []
    for name in models:
        fit, scaler, is_paper = ZOO[name]
        pp = Preprocessor(SPECS[spec_key], scaler=scaler).fit(inner_tr)
        Xtr, Xva, Xte = pp.transform(inner_tr), pp.transform(inner_va), pp.transform(test)
        ytr, yva, yte = inner_tr["y"].to_numpy(), inner_va["y"].to_numpy(), test["y"].to_numpy()
        t0 = time.perf_counter()
        predict, best_params = fit(Xtr, ytr, Xva, yva, seed, budget, dataset)
        fit_s = time.perf_counter() - t0
        p_va, p_te = predict(Xva), predict(Xte)
        base = {"dataset": dataset, "repeat": rep, "fold": fold, "seed": seed, "model": name,
                "paper_reimpl": is_paper, "n_train": len(Xtr), "n_test": len(Xte), "fit_seconds": fit_s,
                "best_params": str(best_params), **threshold_free(yte, p_te)}
        policies = {
            # honest: threshold chosen on inner validation data, applied to the unseen test fold
            "val_youden": THRESHOLD_RULES["youden"](yva, p_va),
            "val_sens80": THRESHOLD_RULES["sens80"](yva, p_va),
            "fixed_0.5": 0.5,
            # what the paper's code does: threshold optimised on the evaluation set itself
            "insample_youden": THRESHOLD_RULES["youden"](yte, p_te),
            "insample_macro_f1": THRESHOLD_RULES["macro_f1"](yte, p_te),
        }
        for pol, thr in policies.items():
            rows.append({**base, "policy": pol, **operating_point(yte, p_te, thr)})
        if "site" in test:
            thr = policies["val_youden"]
            for site, idx in test.groupby("site").indices.items():
                ys, ps = yte[idx], p_te[idx]
                site_rows.append({"dataset": dataset, "repeat": rep, "fold": fold, "model": name, "site": site,
                                  "n": len(ys), "prevalence": ys.mean(), **threshold_free(ys, ps),
                                  **operating_point(ys, ps, thr)})
    return rows, site_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--budget", type=int, default=20, help="Optuna trials per tuned model per fold")
    ap.add_argument("--models", nargs="+", default=list(ZOO))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    df, spec_key = load_dataset(a.dataset)
    strat = (df["site"].astype(str) + df["y"].astype(str)) if "site" in df else df["y"]
    cv = RepeatedStratifiedKFold(n_splits=a.folds, n_repeats=a.repeats, random_state=42)
    splits = [(i // a.folds, i % a.folds, tr, te) for i, (tr, te) in enumerate(cv.split(df, strat))]
    t0 = time.perf_counter()
    out = Parallel(n_jobs=a.jobs, verbose=5)(
        delayed(run_fold)(df, spec_key, a.dataset, r, f, tr, te, a.models, a.budget) for r, f, tr, te in splits)
    rows = [r for o in out for r in o[0]]
    site_rows = [r for o in out for r in o[1]]
    RESULTS.mkdir(exist_ok=True)
    stem = f"p1_{a.dataset}{a.tag}"
    outputs = [RESULTS / f"{stem}_folds.csv"]
    pd.DataFrame(rows).to_csv(outputs[0], index=False)
    if site_rows:
        outputs.append(RESULTS / f"{stem}_persite.csv")
        pd.DataFrame(site_rows).to_csv(outputs[1], index=False)
    record(outputs, {**vars(a), "cv_random_state": 42, "wall_seconds": round(time.perf_counter() - t0, 1)})
    print(f"wrote {[str(o) for o in outputs]} in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()
