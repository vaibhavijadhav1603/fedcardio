"""Privacy attack evaluation: gradient inversion (server view) and membership inference (model release).

python -m experiments.run_attacks  ->  results/p2_attacks.csv
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from fl_engine.attacks.attacks import (
    invert_lr_update, lr_single_record_update, membership_inference_auc, relative_error,
)
from fl_engine.data.federated import fit_federated
from fl_engine.data.preprocess import SPECS
from fl_engine.models.nets import LogReg
from fl_engine.sim import Client, FLConfig, run_federated

from .common import RESULTS, load_dataset, record
from .run_federated import dirichlet_sites


def gradient_inversion(seed: int = 0, n_records: int = 200) -> list[dict]:
    df, spec_key = load_dataset("uci")
    sites = {s: g for s, g in df.groupby("site")}
    pp = fit_federated(list(sites.values()), SPECS[spec_key])
    X = pp.transform(df)
    y = df.y.to_numpy().astype(float)
    rng = np.random.default_rng(seed)
    model = LogReg(X.shape[1])
    rows = []
    for _ in range(n_records):
        idx = rng.choice(len(X), size=4, replace=False)  # 4 clients, each sends a 1-record update
        ups = [lr_single_record_update(model, X[i], y[i]) for i in idx]
        target = X[idx[0]]
        # what the server can see under each mechanism, attacking client 0's record
        views = {"plain FedAvg": ups[0], "HE (server sees ciphertext; aggregate only)": np.mean(ups, axis=0),
                 "SecAgg (aggregate only)": np.mean(ups, axis=0)}
        for sigma in (0.01, 0.1, 1.0):
            clip = 1.0
            u = ups[0] / max(1.0, np.linalg.norm(ups[0]) / clip)
            views[f"local Gaussian noise sigma={sigma}"] = u + rng.normal(0, sigma * clip, u.shape)
        for name, v in views.items():
            rows.append({"attack": "gradient_inversion_lr", "mechanism": name,
                         "relative_error": relative_error(target, invert_lr_update(v))})
    return rows


def membership_inference(seeds=(0, 1, 2)) -> list[dict]:
    df, spec_key = load_dataset("cardio")
    rows = []
    for seed in seeds:
        data = dirichlet_sites(df, 4, 0.5, seed)
        # deliberately small client datasets + a high-capacity model so plain training can overfit
        small = {s: (tr.sample(n=min(300, len(tr)), random_state=seed), va, te) for s, (tr, va, te) in data.items()}
        pp = fit_federated([v[0] for v in small.values()], SPECS[spec_key])
        clients = [Client(s, pp.transform(tr), tr.y.to_numpy().astype(np.float32), pp.transform(va),
                          va.y.to_numpy().astype(np.float32)) for s, (tr, va, te) in small.items()]
        X_in = np.vstack([c.X for c in clients])
        y_in = np.concatenate([c.y for c in clients])
        out = pd.concat([te for _, _, te in small.values()]).sample(n=len(X_in), random_state=seed)
        X_out, y_out = pp.transform(out), out.y.to_numpy().astype(np.float32)
        base = dict(model="mlp", rounds=60, local_epochs=10, lr=0.01, batch_size=64, weight_decay=0.0,
                    eval_every=1000, seed=seed)
        settings = {"plain FedAvg": {}, "HE": {"privacy": "he"}, "SecAgg": {"privacy": "secagg"},
                    **{f"DP-SGD eps={e:g}": {"privacy": "dpsgd", "dp_epsilon": e, "local_epochs": 1,
                                             "dp_sample_rate": 0.2, "dp_lr": 0.5} for e in (1, 8, math.inf)}}
        for name, extra in settings.items():
            res = run_federated(clients, FLConfig(**{**base, **extra}))
            rows.append({"attack": "membership_inference_loss", "mechanism": name, "seed": seed,
                         "attack_auc": membership_inference_auc(res.global_model, X_in, y_in, X_out, y_out),
                         "epsilon": res.epsilon})
    return rows


def main():
    rows = gradient_inversion() + membership_inference()
    out = RESULTS / "p2_attacks.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    record([out], {"script": "run_attacks"})
    d = pd.DataFrame(rows)
    print(d.groupby(["attack", "mechanism"])[["relative_error", "attack_auc"]].agg(["mean", "std"]).round(3))


if __name__ == "__main__":
    main()
