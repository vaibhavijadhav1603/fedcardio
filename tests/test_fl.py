import math

import numpy as np
import pandas as pd
import pytest
import torch
from sklearn.metrics import roc_auc_score
from torch.nn.utils import parameters_to_vector

from fl_engine.data.federated import fit_federated
from fl_engine.data.preprocess import CARDIO, Preprocessor
from fl_engine.models.nets import LogReg, train_torch
from fl_engine.privacy.dpsgd import epsilon_spent, noise_for_budget
from fl_engine.privacy.he_ckks import CKKSAggregator
from fl_engine.privacy.secagg import mask_update, secure_sum
from fl_engine.privacy.svt_paper import svt_filter
from fl_engine.sim import Client, FLConfig, run_federated, run_local_only


def make_clients(n_clients=4, n=200, d=5, seed=0, skew=False):
    rng = np.random.default_rng(seed)
    w = rng.normal(size=d)
    clients = []
    for k in range(n_clients):
        X = rng.normal(loc=(k * 0.5 if skew else 0), size=(n, d)).astype(np.float32)
        y = ((X @ w + rng.normal(0, 0.5, n)) > (k * 0.3 if skew else 0)).astype(np.float32)
        clients.append(Client(f"site{k}", X[:160], y[:160], X[160:], y[160:]))
    return clients


def pooled_val(clients):
    return np.vstack([c.X_val for c in clients]), np.concatenate([c.y_val for c in clients])


# ---------- core FL properties ----------
def test_fedavg_equals_centralised_gd_in_iid_full_participation_limit():
    """One full-batch SGD step per round with n-weighted averaging is exactly one GD step on pooled data."""
    clients = make_clients()
    cfg = FLConfig(model="lr", rounds=5, local_epochs=1, lr=0.5, batch_size=10**6, weight_decay=0.0,
                   local_optimizer="sgd", eval_every=100)
    fl = run_federated(clients, cfg)
    X = np.vstack([c.X for c in clients])
    y = np.concatenate([c.y for c in clients])
    central = LogReg(X.shape[1])
    train_torch(central, X, y, epochs=5, lr=0.5, batch_size=10**6, weight_decay=0.0, optimizer="sgd")
    a = parameters_to_vector(fl.global_model.parameters())
    b = parameters_to_vector(central.parameters())
    assert torch.allclose(a, b, atol=1e-5)


@pytest.mark.parametrize("algorithm", ["fedavg", "fedprox", "scaffold", "fedadam", "fedbn"])
def test_algorithms_converge_on_toy_data(algorithm):
    clients = make_clients(skew=True)
    Xv, yv = pooled_val(clients)
    cfg = FLConfig(model="paper_nn", algorithm=algorithm, rounds=15, local_epochs=5, lr=0.05, batch_size=64,
                   prox_mu=0.1 if algorithm == "fedprox" else 0.0, server_lr=0.1, scaffold_lr=0.1, eval_every=5)
    res = run_federated(clients, cfg, Xv, yv)
    aucs = [roc_auc_score(c.y_val, res.predict(c.name, c.X_val)) for c in clients]
    assert np.mean(aucs) > 0.8
    assert res.history and res.history[-1]["round"] == 15
    assert res.bytes_up > 0
    if algorithm == "fedbn":
        ln = [m.ln.weight.detach() for m in res.site_models.values()]
        assert not torch.allclose(ln[0], ln[1])  # norm params stay local


def test_dropout_and_finetune_and_local_only():
    clients = make_clients()
    res = run_federated(clients, FLConfig(model="lr", rounds=6, local_epochs=2, lr=0.05, batch_size=64,
                                          dropout_prob=0.5, finetune_epochs=3, eval_every=100))
    assert set(res.site_models) == {c.name for c in clients}
    loc = run_local_only(clients, FLConfig(model="lr", rounds=4, local_epochs=8, lr=0.05, batch_size=64))
    assert roc_auc_score(clients[0].y_val, loc.predict("site0", clients[0].X_val)) > 0.8


def test_invalid_combinations_rejected():
    with pytest.raises(ValueError):
        FLConfig(privacy="svt+he")
    with pytest.raises(ValueError):
        FLConfig(algorithm="scaffold", privacy="dpsgd")
    with pytest.raises(ValueError):
        FLConfig(algorithm="fedsgd")


# ---------- privacy mechanisms ----------
def test_he_aggregation_matches_plain_within_error_bound():
    clients = make_clients()
    base = dict(model="paper_nn", rounds=3, local_epochs=2, lr=0.05, batch_size=64, eval_every=100)
    plain = run_federated(clients, FLConfig(**base))
    enc = run_federated(clients, FLConfig(**base, privacy="he"))
    a = parameters_to_vector(plain.global_model.parameters())
    b = parameters_to_vector(enc.global_model.parameters())
    assert torch.max(torch.abs(a - b)) < 1e-3
    assert enc.he["max_abs_error"] < 1e-4
    assert enc.bytes_up > plain.bytes_up  # ciphertext expansion


def test_he_packed_vs_per_tensor_sizes():
    rng = np.random.default_rng(0)
    ups = [rng.normal(size=71).astype(np.float32) for _ in range(2)]
    packed, per = CKKSAggregator(packed=True), CKKSAggregator(packed=False)
    out1 = packed.aggregate(ups, [1, 1], [50, 5, 5, 5, 5, 1])
    out2 = per.aggregate(ups, [1, 1], [50, 5, 5, 5, 5, 1])
    assert np.allclose(out1, out2, atol=1e-4)
    assert per.stats.bytes_up > 3 * packed.stats.bytes_up


def test_secagg_masks_cancel_and_hide_individual_updates():
    rng = np.random.default_rng(0)
    ups = [rng.normal(size=20) for _ in range(4)]
    masked = [mask_update(u, i, [0, 1, 2, 3], round_id=7) for i, u in enumerate(ups)]
    assert np.allclose(secure_sum(masked), np.sum(ups, axis=0), atol=1e-6)
    assert np.abs(masked[0] - ups[0]).mean() > 100  # server cannot read a single update
    res = run_federated(make_clients(), FLConfig(model="lr", privacy="secagg", rounds=3, local_epochs=2,
                                                 lr=0.05, batch_size=64, eval_every=100))
    plain = run_federated(make_clients(), FLConfig(model="lr", rounds=3, local_epochs=2, lr=0.05,
                                                   batch_size=64, eval_every=100))
    assert torch.allclose(parameters_to_vector(res.global_model.parameters()),
                          parameters_to_vector(plain.global_model.parameters()), atol=1e-4)


def test_dp_accountant_sanity():
    s1 = noise_for_budget(1.0, 1e-5, 0.1, 1000)
    s8 = noise_for_budget(8.0, 1e-5, 0.1, 1000)
    assert s1 > s8 > 0
    e_short, e_long = epsilon_spent(s8, 0.1, 100, 1e-5), epsilon_spent(s8, 0.1, 1000, 1e-5)
    assert e_short < e_long == pytest.approx(8.0, rel=0.05)


def test_dpsgd_run_reports_budget_and_noise_hurts_more_at_small_epsilon():
    clients = make_clients(n=400)
    Xv, yv = pooled_val(clients)
    base = dict(model="lr", privacy="dpsgd", rounds=5, local_epochs=1, dp_sample_rate=0.1, dp_lr=0.5,
                eval_every=100, seed=1)
    loose = run_federated(clients, FLConfig(**base, dp_epsilon=50.0), Xv, yv)
    tight = run_federated(clients, FLConfig(**base, dp_epsilon=0.3), Xv, yv)
    assert loose.epsilon == pytest.approx(50.0, rel=0.05) and tight.epsilon == pytest.approx(0.3, rel=0.1)
    auc = lambda r: roc_auc_score(yv, r.global_model(torch.as_tensor(Xv)).detach().numpy())  # noqa: E731
    assert auc(loose) > 0.85 and auc(loose) > auc(tight)
    inf = run_federated(clients, FLConfig(**base, dp_epsilon=math.inf))
    assert inf.epsilon == math.inf


def test_dpsgd_clipping_bounds_per_step_movement():
    """With zero noise, a step moves params by at most lr * clip * (batch / expected batch)."""
    from fl_engine.privacy.dpsgd import dp_sgd_train
    rng = np.random.default_rng(0)
    X = (rng.normal(size=(500, 3)) * 100).astype(np.float32)  # huge gradients
    y = rng.integers(0, 2, 500).astype(np.float32)
    m = LogReg(3)
    before = parameters_to_vector(m.parameters()).detach().clone()
    dp_sgd_train(m, X, y, steps=1, sample_rate=0.1, lr=1.0, clip=0.5, noise_multiplier=0.0, rng=rng)
    moved = torch.norm(parameters_to_vector(m.parameters()) - before).item()
    assert moved <= 0.5 * 1.6  # batch size fluctuates around its expectation (Poisson)


def test_svt_filter_sparsifies_and_clips():
    rng = np.random.default_rng(0)
    delta = rng.normal(0, 1, 100)
    out = svt_filter(delta, fraction=0.3, epsilon=1.0, noise_var=1.0, gamma=0.1, tau=1e-3, total_steps=2, rng=rng)
    assert out.shape == delta.shape
    assert np.count_nonzero(out) <= 30
    assert np.abs(out).max() <= 0.1 * 2 + 1e-9  # clipped to gamma, rescaled by steps
    res = run_federated(make_clients(), FLConfig(model="paper_nn", privacy="svt", rounds=3, local_epochs=2,
                                                 lr=0.05, batch_size=64, eval_every=100))
    assert res.global_model is not None


# ---------- federated preprocessing ----------
def test_federated_preprocessing_matches_pooled_statistics():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"age": rng.normal(50, 8, 300), "height": rng.normal(165, 9, 300),
                       "weight": rng.normal(75, 12, 300), "bmi": rng.normal(27, 4, 300),
                       "ap_hi": rng.normal(128, 15, 300), "ap_lo": rng.normal(82, 9, 300),
                       "sex": rng.integers(0, 2, 300), "smoke": rng.integers(0, 2, 300),
                       "alco": rng.integers(0, 2, 300), "active": rng.integers(0, 2, 300),
                       "cholesterol": rng.integers(1, 4, 300), "gluc": rng.integers(1, 4, 300)})
    sites = [df.iloc[:100], df.iloc[100:180], df.iloc[180:]]
    fed = fit_federated(sites, CARDIO)
    central = Preprocessor(CARDIO).fit(df)
    assert np.allclose(fed.loc_, central.loc_) and np.allclose(fed.scale_, central.scale_)
    assert fed.transform(df).shape == central.transform(df).shape
    fed_mm = fit_federated(sites, CARDIO, scaler="minmax")
    assert fed_mm.transform(df)[:, 0].min() == pytest.approx(0, abs=1e-6)
