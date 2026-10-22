"""Record-level DP-SGD for each client, with an RDP accountant (Opacus).

Guarantee type: **record-level, local to each site** (each hospital privatises its own training).
The (eps, delta) bound holds for any single patient record of that site against everyone who
sees the site's updates (server, other sites, model users), over *all* rounds.
Mechanism: Poisson subsampling with rate q, per-example L2 clipping to C, Gaussian noise
sigma * C added to the summed clipped gradients (Abadi et al. 2016).
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from opacus.accountants import RDPAccountant
from opacus.accountants.utils import get_noise_multiplier
from torch.func import functional_call, grad, vmap


def noise_for_budget(target_eps: float, delta: float, sample_rate: float, steps: int) -> float:
    return float(get_noise_multiplier(target_epsilon=target_eps, target_delta=delta, sample_rate=sample_rate,
                                      steps=steps, accountant="rdp"))


def epsilon_spent(noise_multiplier: float, sample_rate: float, steps: int, delta: float) -> float:
    acc = RDPAccountant()
    acc.history = [(noise_multiplier, sample_rate, steps)]
    return float(acc.get_epsilon(delta))


def dp_sgd_train(model: torch.nn.Module, X: np.ndarray, y: np.ndarray, *, steps: int, sample_rate: float,
                 lr: float, clip: float, noise_multiplier: float, rng: np.random.Generator,
                 pos_weight: float | None = None, prox_mu: float = 0.0, prox_ref=None) -> torch.nn.Module:
    """`steps` DP-SGD steps with Poisson sampling. Uses plain SGD (the accountant assumes nothing
    about the optimiser, but post-processing by Adam is also fine; SGD keeps it simple)."""
    params = {k: v.detach() for k, v in model.named_parameters()}
    Xt, yt = torch.as_tensor(X, dtype=torch.float32), torch.as_tensor(y, dtype=torch.float32)
    pw = torch.tensor(pos_weight) if pos_weight is not None else None

    def loss_one(p, x, t):
        out = functional_call(model, p, (x.unsqueeze(0),))
        return F.binary_cross_entropy_with_logits(out, t.unsqueeze(0), pos_weight=pw)

    per_ex_grad = vmap(grad(loss_one), in_dims=(None, 0, 0))
    n = len(Xt)
    expected = max(1.0, sample_rate * n)
    gen = torch.Generator().manual_seed(int(rng.integers(2**31)))
    for _ in range(steps):
        mask = rng.random(n) < sample_rate
        idx = np.flatnonzero(mask)
        summed = {k: torch.zeros_like(v) for k, v in params.items()}
        if len(idx):
            g = per_ex_grad(params, Xt[idx], yt[idx])
            norms = torch.sqrt(sum((gk.reshape(len(idx), -1) ** 2).sum(1) for gk in g.values()))
            factor = (clip / (norms + 1e-12)).clamp(max=1.0)
            for k in summed:
                summed[k] = (g[k] * factor.view(-1, *[1] * (g[k].dim() - 1))).sum(0)
        new = {}
        for k, v in params.items():
            noisy = (summed[k] + noise_multiplier * clip * torch.randn(v.shape, generator=gen)) / expected
            if prox_mu > 0 and prox_ref is not None:
                noisy = noisy + prox_mu * (v - prox_ref[k])
            new[k] = v - lr * noisy
        params = new
    with torch.no_grad():
        for k, v in model.named_parameters():
            v.copy_(params[k])
    return model
