"""Shared experiment utilities: dataset registry, provenance manifest."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fl_engine.data.loaders import load_cardio70k, load_uci_heart
from fl_engine.data.partition import subsample_prevalence

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
LOWPREV = 0.064  # base paper's prevalence (42,033 / 660,427 from Table 1, rounded)


def load_dataset(name: str) -> tuple[pd.DataFrame, str]:
    """Returns (dataframe with `y` and optionally `site`, FeatureSpec key)."""
    if name == "uci":
        return load_uci_heart(), "uci_main"
    if name == "uci_full":
        return load_uci_heart(), "uci_full"
    if name == "cardio":
        return load_cardio70k(), "cardio"
    if name == "cardio_lowprev":
        return subsample_prevalence(load_cardio70k(), LOWPREV, seed=2026), "cardio"
    raise KeyError(name)


def git_state() -> dict:
    def run(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "fl_engine", "experiments"))}


def record(outputs: list[Path], params: dict) -> None:
    """Append a provenance entry (commit, params, command, sha256 of outputs) to results/manifest.json."""
    mf = RESULTS / "manifest.json"
    entries = json.loads(mf.read_text()) if mf.exists() else []
    data_mf = ROOT / "data" / "raw" / "MANIFEST.json"
    entries.append({
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": " ".join([Path(sys.executable).name, *sys.argv]),
        **git_state(),
        "params": params,
        "data_sha256": json.loads(data_mf.read_text()) if data_mf.exists() else None,
        "outputs": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in outputs},
    })
    mf.write_text(json.dumps(entries, indent=2))
