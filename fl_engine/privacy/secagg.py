"""Additive-masking secure aggregation (Bonawitz et al. 2017, simplified, no dropout recovery).

Every pair of clients (i, j) derives a shared mask from a pairwise seed (stand-in for a
Diffie-Hellman key agreement); client i adds it and client j subtracts it, so masks cancel in
the sum. The server learns only the sum of updates.
Limitations of this demonstrator: no dropout recovery (Shamir secret sharing of seeds), no
malicious-server protection, and masking happens over floats (real SecAgg works over a finite
field with quantised updates). It protects updates against an honest-but-curious server only.
"""
from __future__ import annotations

import hashlib

import numpy as np


def _pair_seed(round_id: int, i: int, j: int, secret: bytes) -> int:
    h = hashlib.sha256(secret + f"{round_id}:{min(i, j)}:{max(i, j)}".encode()).digest()
    return int.from_bytes(h[:8], "little")


def mask_update(update: np.ndarray, client: int, participants: list[int], round_id: int,
                secret: bytes = b"demo-shared-secret", scale: float = 1e3) -> np.ndarray:
    masked = update.astype(np.float64).copy()
    for other in participants:
        if other == client:
            continue
        m = np.random.default_rng(_pair_seed(round_id, client, other, secret)).normal(0, scale, update.shape)
        masked += m if client < other else -m
    return masked


def secure_sum(masked_updates: list[np.ndarray]) -> np.ndarray:
    return np.sum(masked_updates, axis=0)
