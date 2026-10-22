"""Basic privacy attacks used to sanity-check what each mechanism does and does not protect.

1. Gradient inversion against a single-record logistic-regression update. For a linear model,
   grad_w = (p - y) x and grad_b = (p - y), so x = grad_w / grad_b exactly. A server that sees an
   individual plaintext update recovers the record. HE/SecAgg hide individual updates from the
   server (only the aggregate is visible). DP noise degrades reconstruction.
2. Loss-threshold membership inference (Yeom et al. 2018) against the released model:
   attack score = -loss; AUC 0.5 means no measurable leakage. HE/SecAgg do not change the
   released model, so they cannot reduce this; DP-SGD can.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score

from ..models.nets import LogReg


def lr_single_record_update(model: LogReg, x: np.ndarray, y: float, lr: float = 0.1) -> np.ndarray:
    m = LogReg(len(x))
    m.load_state_dict(model.state_dict())
    out = m(torch.as_tensor(x[None], dtype=torch.float32))
    F.binary_cross_entropy_with_logits(out, torch.tensor([y], dtype=torch.float32)).backward()
    return -lr * torch.cat([m.fc.weight.grad.ravel(), m.fc.bias.grad.ravel()]).numpy()


def invert_lr_update(update: np.ndarray) -> np.ndarray:
    """Analytic inversion: x_hat = delta_w / delta_b."""
    db = update[-1]
    return update[:-1] / db if abs(db) > 1e-12 else np.zeros(len(update) - 1)


def relative_error(x: np.ndarray, x_hat: np.ndarray) -> float:
    return float(np.linalg.norm(x - x_hat) / (np.linalg.norm(x) + 1e-12))


def membership_inference_auc(model: torch.nn.Module, X_in: np.ndarray, y_in: np.ndarray,
                             X_out: np.ndarray, y_out: np.ndarray) -> float:
    model.eval()
    with torch.no_grad():
        def losses(X, y):
            return F.binary_cross_entropy_with_logits(model(torch.as_tensor(X, dtype=torch.float32)),
                                                      torch.as_tensor(y, dtype=torch.float32),
                                                      reduction="none").numpy()
        li, lo = losses(X_in, y_in), losses(X_out, y_out)
    scores = np.concatenate([-li, -lo])
    labels = np.concatenate([np.ones(len(li)), np.zeros(len(lo))])
    return float(roc_auc_score(labels, scores))
