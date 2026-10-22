"""PyTorch models and a shared training loop (also used by the FL simulator)."""
from __future__ import annotations

import copy

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class PaperMLP(nn.Module):
    """Re-implementation of Sharma et al.'s `SimpleMLP`: d -> 5 -> LayerNorm -> ReLU -> 1.

    With d = 10 this has 71 trainable parameters (the paper reports 66; see docs/SPEC.md).
    """

    def __init__(self, input_dim: int, hidden: int = 5):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, hidden)
        self.ln = nn.LayerNorm(hidden)
        self.fc2 = nn.Linear(hidden, 1)
        for layer in (self.fc1, self.fc2):
            nn.init.xavier_uniform_(layer.weight)
            nn.init.zeros_(layer.bias)

    def forward(self, x):
        return self.fc2(F.relu(self.ln(self.fc1(x)))).squeeze(-1)


class LogReg(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.fc = nn.Linear(input_dim, 1)
        nn.init.zeros_(self.fc.weight)
        nn.init.zeros_(self.fc.bias)

    def forward(self, x):
        return self.fc(x).squeeze(-1)


class TunableMLP(nn.Module):
    def __init__(self, input_dim: int, hidden: int = 32, layers: int = 2, dropout: float = 0.1,
                 norm: bool = True):
        super().__init__()
        mods, d = [], input_dim
        for _ in range(layers):
            mods += [nn.Linear(d, hidden)]
            if norm:
                mods += [nn.LayerNorm(hidden)]
            mods += [nn.ReLU(), nn.Dropout(dropout)]
            d = hidden
        mods += [nn.Linear(d, 1)]
        self.net = nn.Sequential(*mods)

    def forward(self, x):
        return self.net(x).squeeze(-1)


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def focal_loss(logits, y, gamma: float = 2.0, pos_weight: float | None = None):
    bce = F.binary_cross_entropy_with_logits(logits, y, reduction="none")
    p_t = torch.exp(-bce)
    loss = (1 - p_t) ** gamma * bce
    if pos_weight is not None:
        loss = loss * torch.where(y > 0.5, pos_weight, 1.0)
    return loss.mean()


def make_loss(kind: str = "bce", pos_weight: float | None = None, gamma: float = 2.0):
    if kind == "bce":
        pw = None if pos_weight is None else torch.tensor(pos_weight)
        return lambda logits, y: F.binary_cross_entropy_with_logits(logits, y, pos_weight=pw)
    if kind == "focal":
        return lambda logits, y: focal_loss(logits, y, gamma, pos_weight)
    raise ValueError(kind)


def train_torch(model: nn.Module, X: np.ndarray, y: np.ndarray, *, epochs: int, lr: float,
                batch_size: int, weight_decay: float = 1e-2, seed: int = 0,
                X_val: np.ndarray | None = None, y_val: np.ndarray | None = None,
                patience: int | None = None, loss: str = "bce", pos_weight: float | None = None,
                prox_mu: float = 0.0, prox_ref: list[torch.Tensor] | None = None,
                grad_hook=None, optimizer: str = "adamw") -> nn.Module:
    """AdamW training (matches the paper's learner). Optional early stopping on val loss,
    FedProx proximal term, and a per-step gradient hook (used by SCAFFOLD)."""
    g = torch.Generator().manual_seed(seed)
    Xt, yt = torch.as_tensor(X, dtype=torch.float32), torch.as_tensor(y, dtype=torch.float32)
    opt = (torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay) if optimizer == "adamw"
           else torch.optim.SGD(model.parameters(), lr=lr))
    crit = make_loss(loss, pos_weight)
    best, best_loss, bad = None, float("inf"), 0
    n = len(Xt)
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(n, generator=g)
        for s in range(0, n, batch_size):
            idx = perm[s:s + batch_size]
            opt.zero_grad()
            out = crit(model(Xt[idx]), yt[idx])
            if prox_mu > 0 and prox_ref is not None:
                out = out + prox_mu / 2 * sum(((p - r) ** 2).sum() for p, r in zip(model.parameters(), prox_ref))
            out.backward()
            if grad_hook is not None:
                grad_hook(model)
            opt.step()
        if patience is not None and X_val is not None:
            vl = val_loss(model, X_val, y_val)
            if vl < best_loss - 1e-5:
                best_loss, best, bad = vl, copy.deepcopy(model.state_dict()), 0
            else:
                bad += 1
                if bad >= patience:
                    break
    if best is not None:
        model.load_state_dict(best)
    return model


@torch.no_grad()
def predict_proba(model: nn.Module, X: np.ndarray) -> np.ndarray:
    model.eval()
    return torch.sigmoid(model(torch.as_tensor(X, dtype=torch.float32))).numpy()


@torch.no_grad()
def val_loss(model: nn.Module, X: np.ndarray, y: np.ndarray) -> float:
    model.eval()
    logits = model(torch.as_tensor(X, dtype=torch.float32))
    return F.binary_cross_entropy_with_logits(logits, torch.as_tensor(y, dtype=torch.float32)).item()
