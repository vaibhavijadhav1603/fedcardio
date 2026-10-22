import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from fl_engine.models import zoo


@pytest.mark.parametrize("name", list(zoo.ZOO))
def test_every_zoo_model_fits_and_predicts(name, monkeypatch):
    monkeypatch.setitem(zoo.PAPER_NN_EPOCHS, "toy", 40)
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 5)).astype(np.float32)
    y = (X[:, 0] - X[:, 1] + rng.normal(0, 0.5, 300) > 0).astype(int)
    fit, scaler, is_paper = zoo.ZOO[name]
    predict, params = fit(X[:200], y[:200], X[200:], y[200:], seed=0, budget=2, dataset="toy")
    p = predict(X[200:])
    assert p.shape == (100,) and np.all((p >= 0) & (p <= 1))
    assert roc_auc_score(y[200:], p) > 0.75
    assert is_paper == name.startswith("paper_")
    assert scaler in ("standard", "minmax")
    assert isinstance(params, dict)
