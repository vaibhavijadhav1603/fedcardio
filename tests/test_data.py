import pytest

from fl_engine.data.download import RAW
from fl_engine.data.loaders import UCI_SITES, load_cardio70k, load_uci_heart

pytestmark = pytest.mark.skipif(
    not (RAW / "uci_heart").exists(), reason="run `python -m fl_engine.data.download` first"
)


def test_uci_sites_and_sizes():
    df = load_uci_heart()
    assert set(df["site"]) == set(UCI_SITES)
    assert df.groupby("site").size().to_dict() == {
        "cleveland": 303, "hungarian": 294, "switzerland": 123, "va_long_beach": 200,
    }
    assert set(df["y"].unique()) == {0, 1}
    assert "num" not in df.columns


def test_uci_zero_cholesterol_is_missing():
    df = load_uci_heart()
    assert (df["chol"] == 0).sum() == 0
    assert df.loc[df.site == "switzerland", "chol"].isna().all()


def test_cardio_cleaning():
    raw, clean = load_cardio70k(clean=False), load_cardio70k()
    assert len(raw) == 70000
    assert 60000 < len(clean) < 70000
    assert clean["ap_hi"].gt(clean["ap_lo"]).all()
    assert clean["age"].between(25, 70).all()
