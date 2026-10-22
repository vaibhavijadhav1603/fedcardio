"""Phase 0 feasibility checks: the privacy/FL libraries import and behave on this machine."""
import numpy as np


def test_ckks_roundtrip_with_paper_params():
    import tenseal as ts

    ctx = ts.context(ts.SCHEME_TYPE.CKKS, poly_modulus_degree=8192, coeff_mod_bit_sizes=[60, 40, 40])
    ctx.global_scale = 2**40
    rng = np.random.default_rng(0)
    updates = [rng.normal(0, 0.1, 71) for _ in range(4)]
    enc_sum = sum((ts.ckks_vector(ctx, u.tolist()) for u in updates[1:]), ts.ckks_vector(ctx, updates[0].tolist()))
    avg = np.array((enc_sum * (1 / 4)).decrypt())
    assert np.max(np.abs(avg - np.mean(updates, axis=0))) < 1e-4


def test_fl_and_dp_libraries_import():
    import flwr
    import opacus

    assert flwr.__version__.startswith("1.")
    assert opacus.__version__.startswith("1.")
