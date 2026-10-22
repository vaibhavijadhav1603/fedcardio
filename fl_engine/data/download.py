"""Download the public datasets into data/raw/ and record their SHA-256 hashes.

Usage: python -m fl_engine.data.download
Raw files are never committed (data/raw/ is gitignored).
"""
from __future__ import annotations

import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

SOURCES = {
    "uci_heart": {
        "url": "https://archive.ics.uci.edu/static/public/45/heart+disease.zip",
        "members": [
            "processed.cleveland.data",
            "processed.hungarian.data",
            "processed.switzerland.data",
            "processed.va.data",
        ],
    },
    "cardio70k": {
        "url": "https://www.kaggle.com/api/v1/datasets/download/sulianova/cardiovascular-disease-dataset",
        "members": ["cardio_train.csv"],
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def fetch(name: str, force: bool = False) -> dict[str, str]:
    spec = SOURCES[name]
    out_dir = RAW / name
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [out_dir / m for m in spec["members"]]
    if force or not all(t.exists() for t in targets):
        req = urllib.request.Request(spec["url"], headers={"User-Agent": "fedcardio/0.1"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = {Path(n).name: n for n in zf.namelist()}
            for m in spec["members"]:
                if m not in names:
                    raise FileNotFoundError(f"{m} not in archive from {spec['url']}")
                (out_dir / m).write_bytes(zf.read(names[m]))
    return {t.name: sha256(t) for t in targets}


def main() -> None:
    manifest = {name: {"url": SOURCES[name]["url"], "sha256": fetch(name)} for name in SOURCES}
    (RAW / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
