"""Pure-PyTorch federated learning simulator.

Algorithms: fedavg, fedprox, scaffold, fedadam, fedbn (+ optional local fine-tuning).
Privacy: none | svt (paper) | dpsgd (record-level, RDP-accounted) | he (CKKS) | secagg,
and the valid combinations dpsgd+he, dpsgd+secagg.
Invalid combinations are rejected (see VALID_PRIVACY and docs/THREAT_MODEL.md).
"""
from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import torch
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from .models.nets import LogReg, PaperMLP, TunableMLP, predict_proba, set_seed, train_torch
from .privacy.dpsgd import dp_sgd_train, epsilon_spent, noise_for_budget
from .privacy.he_ckks import CKKSAggregator
from .privacy.secagg import mask_update, secure_sum
from .privacy.svt_paper import PAPER_SVT, svt_filter

ALGORITHMS = ("fedavg", "fedprox", "scaffold", "fedadam", "fedbn")
VALID_PRIVACY = ("none", "svt", "dpsgd", "he", "secagg", "dpsgd+he", "dpsgd+secagg")
# svt+he / svt+secagg are not offered: SVT's sparsification is a client-side release mechanism
# without an accountant, so combining it adds cost without a meaningful guarantee.


@dataclass
class FLConfig:
    model: str = "paper_nn"           # paper_nn | lr | mlp
    algorithm: str = "fedavg"
    privacy: str = "none"
    rounds: int = 50
    local_epochs: int = 20
    lr: float = 0.01
    batch_size: int = 20000
    weight_decay: float = 1e-2
    local_optimizer: str = "adamw"   # adamw (paper) | sgd
    prox_mu: float = 0.0
    scaffold_lr: float = 0.1
    server_lr: float = 0.05           # FedAdam
    server_beta1: float = 0.9
    server_beta2: float = 0.99
    server_tau: float = 1e-3
    loss: str = "bce"                 # bce | focal
    class_weight: bool = False        # pos_weight = n_neg / n_pos (per client)
    dp_epsilon: float = 3.0
    dp_delta: float = 1e-5
    dp_clip: float = 1.0
    dp_sample_rate: float = 0.1
    dp_lr: float = 0.5
    he_packed: bool = True
    dropout_prob: float = 0.0
    finetune_epochs: int = 0
    weighting: str = "n"              # n | uniform
    eval_every: int = 5
    seed: int = 0

    def __post_init__(self):
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"unknown algorithm {self.algorithm}")
        if self.privacy not in VALID_PRIVACY:
            raise ValueError(f"privacy '{self.privacy}' is not a valid combination; choose from {VALID_PRIVACY}")
        if self.algorithm == "scaffold" and "dpsgd" in self.privacy:
            raise ValueError("SCAFFOLD control variates would leak un-noised gradient information; not combined with DP-SGD here")


@dataclass
class Client:
    name: str
    X: np.ndarray
    y: np.ndarray
    X_val: np.ndarray
    y_val: np.ndarray


@dataclass
class FLResult:
    config: dict
    history: list = field(default_factory=list)
    bytes_up: int = 0
    bytes_down: int = 0
    wall_seconds: float = 0.0
    epsilon: float | None = None
    he: dict | None = None
    global_model: torch.nn.Module | None = None
    site_models: dict | None = None

    def model_for(self, site: str) -> torch.nn.Module:
        return (self.site_models or {}).get(site, self.global_model)

    def predict(self, site: str, X: np.ndarray) -> np.ndarray:
        return predict_proba(self.model_for(site), X)


def build_model(kind: str, d: int) -> torch.nn.Module:
    if kind == "paper_nn":
        return PaperMLP(d)
    if kind == "lr":
        return LogReg(d)
    if kind == "mlp":
        return TunableMLP(d, hidden=16, layers=2, dropout=0.1)
    raise ValueError(kind)


def _norm_mask(model: torch.nn.Module) -> torch.Tensor:
    """Boolean vector over flattened params: True for normalisation-layer params (kept local in FedBN)."""
    parts = []
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.LayerNorm | torch.nn.BatchNorm1d):
            parts += [(f"{name}.{pn}", p.numel()) for pn, p in mod.named_parameters(recurse=False)]
    norm_names = {n for n, _ in parts}
    return torch.cat([torch.full((p.numel(),), n in norm_names, dtype=torch.bool)
                      for n, p in model.named_parameters()])


def run_federated(clients: list[Client], cfg: FLConfig, X_monitor=None, y_monitor=None,
                  on_round=None, should_stop=None) -> FLResult:
    """on_round(entry) is called after each evaluation; should_stop() -> True aborts between rounds."""
    from sklearn.metrics import roc_auc_score

    set_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    d = clients[0].X.shape[1]
    global_model = build_model(cfg.model, d)
    gvec = parameters_to_vector(global_model.parameters()).detach().clone()
    P = gvec.numel()
    norm_mask = _norm_mask(global_model) if cfg.algorithm == "fedbn" else torch.zeros(P, dtype=torch.bool)
    local_norm = {c.name: gvec[norm_mask].clone() for c in clients}
    he = CKKSAggregator(packed=cfg.he_packed) if "he" in cfg.privacy else None
    res = FLResult(config=asdict(cfg))

    # SCAFFOLD control variates
    c_global = torch.zeros(P)
    c_local = {c.name: torch.zeros(P) for c in clients}
    # FedAdam server state
    m_t, v_t = torch.zeros(P), torch.zeros(P)
    # DP-SGD noise calibrated so that every client meets the target over ALL rounds
    dp_sigma, dp_steps_per_round = None, None
    if "dpsgd" in cfg.privacy:
        dp_steps_per_round = max(1, int(round(cfg.local_epochs / cfg.dp_sample_rate)))
        total_steps = cfg.rounds * dp_steps_per_round
        dp_sigma = (0.0 if np.isinf(cfg.dp_epsilon) else
                    noise_for_budget(cfg.dp_epsilon, cfg.dp_delta, cfg.dp_sample_rate, total_steps))
        res.epsilon = (float("inf") if dp_sigma == 0 else
                       epsilon_spent(dp_sigma, cfg.dp_sample_rate, total_steps, cfg.dp_delta))

    t_start = time.perf_counter()
    for rnd in range(cfg.rounds):
        alive = [c for c in clients if rng.random() >= cfg.dropout_prob] or [clients[rng.integers(len(clients))]]
        deltas, weights, new_c = [], [], {}
        for c in alive:
            local = copy.deepcopy(global_model)
            start = gvec.clone()
            if cfg.algorithm == "fedbn":
                start[norm_mask] = local_norm[c.name]
            vector_to_parameters(start.clone(), local.parameters())  # clone: params would alias `start`
            pw = None
            if cfg.class_weight:
                pw = float((c.y == 0).sum() / max(1, (c.y == 1).sum()))
            if "dpsgd" in cfg.privacy:
                ref = {k: v.detach().clone() for k, v in local.named_parameters()} if cfg.prox_mu else None
                dp_sgd_train(local, c.X, c.y, steps=dp_steps_per_round, sample_rate=cfg.dp_sample_rate,
                             lr=cfg.dp_lr, clip=cfg.dp_clip, noise_multiplier=dp_sigma, rng=rng,
                             pos_weight=pw, prox_mu=cfg.prox_mu, prox_ref=ref)
                steps = dp_steps_per_round
            elif cfg.algorithm == "scaffold":
                corr = c_global - c_local[c.name]

                def hook(m, corr=corr):
                    s = 0
                    for p in m.parameters():
                        n = p.numel()
                        p.grad.add_(corr[s:s + n].view_as(p))
                        s += n
                train_torch(local, c.X, c.y, epochs=cfg.local_epochs, lr=cfg.scaffold_lr,
                            batch_size=cfg.batch_size, seed=cfg.seed * 1000 + rnd, loss=cfg.loss,
                            pos_weight=pw, grad_hook=hook, optimizer="sgd")
                steps = cfg.local_epochs * int(np.ceil(len(c.X) / cfg.batch_size))
            else:
                ref = [p.detach().clone() for p in local.parameters()] if cfg.prox_mu > 0 else None
                train_torch(local, c.X, c.y, epochs=cfg.local_epochs, lr=cfg.lr, batch_size=cfg.batch_size,
                            weight_decay=cfg.weight_decay, seed=cfg.seed * 1000 + rnd, loss=cfg.loss,
                            pos_weight=pw, prox_mu=cfg.prox_mu, prox_ref=ref, optimizer=cfg.local_optimizer)
                steps = cfg.local_epochs * int(np.ceil(len(c.X) / cfg.batch_size))
            lvec = parameters_to_vector(local.parameters()).detach()
            if cfg.algorithm == "fedbn":
                local_norm[c.name] = lvec[norm_mask].clone()
            delta = (lvec - start).numpy()
            if cfg.privacy == "svt":
                delta = svt_filter(delta, total_steps=steps, rng=rng,
                                   **PAPER_SVT["lr" if cfg.model == "lr" else "nn"])
            if cfg.algorithm == "scaffold":
                ci_new = c_local[c.name] - c_global + (start - lvec) / (steps * cfg.scaffold_lr)
                new_c[c.name] = ci_new
            deltas.append(delta.astype(np.float32))
            weights.append(1.0 if cfg.weighting == "uniform" else float(len(c.X)))

        # ---------------- aggregation ----------------
        shapes = [p.numel() for p in global_model.parameters()]
        if he is not None:
            agg = he.aggregate(deltas, weights, shapes)
        elif "secagg" in cfg.privacy:
            ids = list(range(len(alive)))
            masked = [mask_update(dl * w, i, ids, rnd) for i, (dl, w) in enumerate(zip(deltas, weights))]
            agg = (secure_sum(masked) / sum(weights)).astype(np.float32)
            res.bytes_up += sum(m.nbytes // 2 for m in masked)  # float32 on the wire
            res.bytes_down += P * 4 * len(alive)
        else:
            agg = (np.sum([dl * w for dl, w in zip(deltas, weights)], axis=0) / sum(weights)).astype(np.float32)
            res.bytes_up += P * 4 * len(alive)
            res.bytes_down += P * 4 * len(alive)
        agg_t = torch.from_numpy(agg)
        agg_t[norm_mask] = 0.0

        if cfg.algorithm == "fedadam":
            m_t = cfg.server_beta1 * m_t + (1 - cfg.server_beta1) * agg_t
            v_t = cfg.server_beta2 * v_t + (1 - cfg.server_beta2) * agg_t ** 2
            gvec = gvec + cfg.server_lr * m_t / (torch.sqrt(v_t) + cfg.server_tau)
        else:
            gvec = gvec + agg_t
        if cfg.algorithm == "scaffold":
            for name, ci in new_c.items():
                c_global += (ci - c_local[name]) / len(clients)
                c_local[name] = ci
            res.bytes_up += P * 4 * len(alive)    # control variates double the traffic
            res.bytes_down += P * 4 * len(alive)
        vector_to_parameters(gvec.clone(), global_model.parameters())

        if X_monitor is not None and ((rnd + 1) % cfg.eval_every == 0 or rnd == cfg.rounds - 1):
            p = predict_proba(global_model, X_monitor)
            auc = roc_auc_score(y_monitor, p) if len(np.unique(y_monitor)) == 2 else float("nan")
            entry = {"round": rnd + 1, "val_auroc": auc, "participants": len(alive),
                     "elapsed_s": time.perf_counter() - t_start, "bytes_up": res.bytes_up}
            res.history.append(entry)
            if on_round is not None:
                on_round(entry)
        if should_stop is not None and should_stop():
            break

    res.global_model = global_model
    if cfg.algorithm == "fedbn" or cfg.finetune_epochs > 0:
        res.site_models = {}
        for c in clients:
            m = copy.deepcopy(global_model)
            v = gvec.clone()
            if cfg.algorithm == "fedbn":
                v[norm_mask] = local_norm[c.name]
            vector_to_parameters(v.clone(), m.parameters())
            if cfg.finetune_epochs > 0:
                if "dpsgd" in cfg.privacy:
                    raise ValueError("fine-tuning after DP-SGD would need its own privacy accounting")
                train_torch(m, c.X, c.y, epochs=cfg.finetune_epochs, lr=cfg.lr * 0.5,
                            batch_size=cfg.batch_size, weight_decay=cfg.weight_decay, seed=cfg.seed,
                            X_val=c.X_val, y_val=c.y_val, patience=5)
            res.site_models[c.name] = m
    if he is not None:
        res.he = {k: v for k, v in asdict(he.stats).items() if k != "per_round"}
        res.bytes_up, res.bytes_down = he.stats.bytes_up, he.stats.bytes_down
    res.wall_seconds = time.perf_counter() - t_start
    return res


def run_local_only(clients: list[Client], cfg: FLConfig) -> FLResult:
    """Each site trains alone on its own data (no collaboration) - the FL motivation baseline."""
    res = FLResult(config={**asdict(cfg), "algorithm": "local_only"}, site_models={})
    t0 = time.perf_counter()
    for c in clients:
        set_seed(cfg.seed)
        m = build_model(cfg.model, c.X.shape[1])
        train_torch(m, c.X, c.y, epochs=cfg.rounds * cfg.local_epochs // 4, lr=cfg.lr,
                    batch_size=cfg.batch_size, weight_decay=cfg.weight_decay, seed=cfg.seed,
                    X_val=c.X_val, y_val=c.y_val, patience=50)
        res.site_models[c.name] = m
    res.global_model = next(iter(res.site_models.values()))
    res.wall_seconds = time.perf_counter() - t0
    return res
