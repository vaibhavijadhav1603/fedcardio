"""CKKS homomorphic aggregation via TenSEAL, with the paper's parameters.

Protects model updates **against the aggregation server** (it only sees ciphertexts). It does
NOT protect against what the final, decrypted model reveals (use DP for that), and assumes the
secret key is held only by the clients (here: one shared client context, as in NVFLARE's setup).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import tenseal as ts


@dataclass
class HEStats:
    encrypt_s: float = 0.0
    aggregate_s: float = 0.0
    decrypt_s: float = 0.0
    bytes_up: int = 0
    bytes_down: int = 0
    max_abs_error: float = 0.0
    per_round: list = field(default_factory=list)


class CKKSAggregator:
    """packed=True encrypts the whole flattened update in one ciphertext (up to 4096 slots);
    packed=False encrypts each parameter tensor separately (closer to NVFLARE's per-layer scheme)."""

    def __init__(self, poly_degree: int = 8192, coeff_mod=(60, 40, 40), scale_bits: int = 40, packed: bool = True):
        self.ctx = ts.context(ts.SCHEME_TYPE.CKKS, poly_modulus_degree=poly_degree, coeff_mod_bit_sizes=list(coeff_mod))
        self.ctx.global_scale = 2**scale_bits
        self.slots = poly_degree // 2
        self.packed = packed
        self.stats = HEStats()

    def _chunks(self, flat: np.ndarray, shapes: list[int]) -> list[np.ndarray]:
        if self.packed:
            return [flat[i:i + self.slots] for i in range(0, len(flat), self.slots)]
        out, s = [], 0
        for n in shapes:
            out.append(flat[s:s + n])
            s += n
        return out

    def aggregate(self, updates: list[np.ndarray], weights: list[float], shapes: list[int]) -> np.ndarray:
        """Each client encrypts w_i * update_i; server sums ciphertexts and multiplies by 1/sum(w);
        clients decrypt. Returns the decrypted weighted mean."""
        t0 = time.perf_counter()
        enc = []
        up = 0
        for u, w in zip(updates, weights):
            cts = [ts.ckks_vector(self.ctx, (c * w).tolist()) for c in self._chunks(u * 1.0, shapes)]
            up += sum(len(c.serialize()) for c in cts)
            enc.append(cts)
        t1 = time.perf_counter()
        acc = enc[0]
        for cts in enc[1:]:
            acc = [a + b for a, b in zip(acc, cts)]
        acc = [a * (1.0 / float(sum(weights))) for a in acc]
        down = sum(len(a.serialize()) for a in acc)
        t2 = time.perf_counter()
        out = np.concatenate([np.array(a.decrypt()) for a in acc])[: len(updates[0])]
        t3 = time.perf_counter()
        exact = np.sum([u * w for u, w in zip(updates, weights)], axis=0) / sum(weights)
        err = float(np.max(np.abs(out - exact)))
        s = self.stats
        s.encrypt_s += t1 - t0
        s.aggregate_s += t2 - t1
        s.decrypt_s += t3 - t2
        s.bytes_up += up
        s.bytes_down += down * len(updates)
        s.max_abs_error = max(s.max_abs_error, err)
        s.per_round.append({"encrypt_s": t1 - t0, "aggregate_s": t2 - t1, "decrypt_s": t3 - t2,
                            "bytes_up_per_client": up / len(updates), "max_abs_error": err})
        return out.astype(np.float32)
