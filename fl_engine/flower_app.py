"""Networked federated training with Flower (one server, one client process per hospital).

The experiments use the in-process simulator (fl_engine.sim) for speed and exact control;
this module runs the same model and FedAvg/FedProx update rule over real gRPC connections, as
in the docker-compose deployment (one container per hospital).

  python -m fl_engine.flower_app server --rounds 10 --min-clients 4 [--strategy fedprox]
  python -m fl_engine.flower_app client --site cleveland --server fl-server:8080

TLS: pass --tls-dir with ca.crt/server.pem/server.key (server) or ca.crt (client); see
scripts/gen_certs.sh. Without it the connection is insecure (local development only).
Each hospital's raw data never leaves its client process; only parameters are exchanged.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import torch
from sklearn.model_selection import train_test_split
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from .data.federated import fit_federated
from .data.loaders import UCI_SITES, load_uci_heart
from .data.preprocess import SPECS
from .eval.metrics import threshold_free
from .models.nets import PaperMLP, predict_proba, train_torch

N_FEATURES = 19  # uci_main schema width


def _site_data(site: str, seed: int = 0):
    """Each client loads only its own hospital's rows. The shared schema statistics are
    agreed beforehand (fit_federated over aggregate statistics); here every client recomputes
    them from the public UCI release for simplicity."""
    df = load_uci_heart()
    parts = {}
    for s, g in df.groupby("site"):
        tr, te = train_test_split(g, test_size=0.2, stratify=g.y, random_state=seed)
        parts[s] = (tr, te)
    pp = fit_federated([tr for tr, _ in parts.values()], SPECS["uci_main"])
    tr, te = parts[site]
    return (pp.transform(tr), tr.y.to_numpy().astype(np.float32), pp.transform(te), te.y.to_numpy().astype(np.float32))


def _get(model) -> list[np.ndarray]:
    return [parameters_to_vector(model.parameters()).detach().numpy().astype(np.float32)]


def _set(model, params) -> None:
    vector_to_parameters(torch.as_tensor(params[0]).clone(), model.parameters())


def run_client(site: str, server: str, tls_dir: str | None):
    import flwr as fl

    X, y, Xt, yt = _site_data(site)

    class HospitalClient(fl.client.NumPyClient):
        def __init__(self):
            self.model = PaperMLP(X.shape[1])

        def get_parameters(self, config):
            return _get(self.model)

        def fit(self, parameters, config):
            _set(self.model, parameters)
            mu = float(config.get("proximal_mu", 0.0))
            ref = [p.detach().clone() for p in self.model.parameters()] if mu > 0 else None
            train_torch(self.model, X, y, epochs=int(config.get("local_epochs", 5)), lr=float(config.get("lr", 0.01)),
                        batch_size=20000, seed=int(config.get("server_round", 0)), prox_mu=mu, prox_ref=ref)
            return _get(self.model), len(X), {"site": site}

        def evaluate(self, parameters, config):
            _set(self.model, parameters)
            p = predict_proba(self.model, Xt)
            loss = float(-np.mean(yt * np.log(p + 1e-7) + (1 - yt) * np.log(1 - p + 1e-7)))
            return loss, len(Xt), {"auroc": float(threshold_free(yt, p)["auroc"])}

    root = Path(tls_dir, "ca.crt").read_bytes() if tls_dir else None
    fl.client.start_client(server_address=server, client=HospitalClient().to_client(), root_certificates=root,
                           insecure=root is None)


def run_server(rounds: int, min_clients: int, strategy: str, address: str, tls_dir: str | None):
    import flwr as fl

    def fit_config(rnd: int):
        return {"server_round": rnd, "local_epochs": 5, "lr": 0.01}

    def weighted_auroc(metrics):
        n = sum(k for k, _ in metrics)
        return {"auroc": sum(k * m["auroc"] for k, m in metrics) / max(n, 1)}

    init = fl.common.ndarrays_to_parameters(_get(PaperMLP(N_FEATURES)))
    common = dict(min_fit_clients=min_clients, min_available_clients=min_clients, min_evaluate_clients=min_clients,
                  on_fit_config_fn=fit_config, evaluate_metrics_aggregation_fn=weighted_auroc, initial_parameters=init)
    strat = (fl.server.strategy.FedProx(proximal_mu=0.01, **common) if strategy == "fedprox"
             else fl.server.strategy.FedAvg(**common))
    certs = None
    if tls_dir:
        d = Path(tls_dir)
        certs = ((d / "ca.crt").read_bytes(), (d / "server.pem").read_bytes(), (d / "server.key").read_bytes())
    hist = fl.server.start_server(server_address=address, config=fl.server.ServerConfig(num_rounds=rounds),
                                  strategy=strat, certificates=certs)
    for rnd, auc in hist.metrics_distributed.get("auroc", []):
        print(f"round {rnd}: federated AUROC {auc:.3f}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="role", required=True)
    s = sub.add_parser("server")
    s.add_argument("--rounds", type=int, default=10)
    s.add_argument("--min-clients", type=int, default=len(UCI_SITES))
    s.add_argument("--strategy", choices=["fedavg", "fedprox"], default="fedavg")
    s.add_argument("--address", default="0.0.0.0:8080")
    s.add_argument("--tls-dir", default=os.environ.get("FL_TLS_DIR"))
    c = sub.add_parser("client")
    c.add_argument("--site", required=True, choices=list(UCI_SITES))
    c.add_argument("--server", default="127.0.0.1:8080")
    c.add_argument("--tls-dir", default=os.environ.get("FL_TLS_DIR"))
    a = ap.parse_args()
    if a.role == "server":
        run_server(a.rounds, a.min_clients, a.strategy, a.address, a.tls_dir)
    else:
        run_client(a.site, a.server, a.tls_dir)


if __name__ == "__main__":
    main()
