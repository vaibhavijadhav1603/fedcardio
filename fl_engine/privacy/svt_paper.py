"""Re-implementation of the paper's client-side SVT filter (NVFLARE `SVTPrivacy`, Apache-2.0 logic).

Faithful to the NVFLARE algorithm used by Sharma et al. (see docs/SPEC.md §2b): updates are
normalised by local steps, candidate coordinates pass a noisy threshold, a fixed fraction is
released with Laplace noise of scale 2*gamma/noise_var, the rest are zeroed.

Privacy note: `epsilon` here is a per-release SVT parameter. Composition over rounds is NOT
accounted (the paper does not do it either), so this module provides **no end-to-end (eps, delta)
guarantee**. It is included only to reproduce the baseline.
"""
from __future__ import annotations

import numpy as np


def svt_filter(delta: np.ndarray, *, fraction: float, epsilon: float, noise_var: float, gamma: float,
               tau: float, total_steps: int, rng: np.random.Generator, replace: bool = True) -> np.ndarray:
    delta_w = delta.astype(np.float64).ravel() / float(total_steps)
    n_upload = int(min(np.ceil(delta_w.size * fraction), delta_w.size))
    lambda_rho = gamma * 2.0 / epsilon
    threshold = tau + rng.laplace(scale=lambda_rho)
    eps_2 = epsilon * (2.0 * n_upload) ** (2.0 / 3.0)
    lambda_nu = gamma * 4.0 * n_upload / eps_2
    accepted: list[int] = []
    candidates = np.arange(delta_w.size)
    clipped = np.abs(np.clip(delta_w, -gamma, gamma))
    while len(accepted) < n_upload and len(candidates):
        nu = rng.laplace(scale=lambda_nu, size=candidates.shape)
        above = (clipped[candidates] + nu) >= threshold
        accepted += candidates[above].tolist()
        candidates = candidates[~above]
    if not accepted:
        return np.zeros_like(delta)
    chosen = rng.choice(accepted, size=n_upload, replace=replace)
    noise = rng.laplace(scale=gamma * 2.0 / noise_var, size=chosen.shape)
    out = np.zeros_like(delta_w)
    out[chosen] = np.clip(delta_w[chosen] + noise, -gamma, gamma)
    return (out * total_steps).reshape(delta.shape).astype(delta.dtype)


# Parameters from the paper (p.7). NN: fraction 0.9, eps 5, NoiseVar 2.5, gamma 0.1, tau 5e-4.
PAPER_SVT = {
    "nn": dict(fraction=0.9, epsilon=5.0, noise_var=2.5, gamma=0.1, tau=5e-4),
    "lr": dict(fraction=0.99, epsilon=1e4, noise_var=1e2, gamma=1e-3, tau=1e-8),
}
