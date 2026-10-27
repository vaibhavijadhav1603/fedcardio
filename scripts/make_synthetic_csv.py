"""Synthetic heart-disease patients in the FedCardio upload schema (UCI Heart columns). Not real patients.

Values come from clinically plausible ranges and the target follows a logistic model of known risk
factors, so a model can learn from it.  Usage: python scripts/make_synthetic_csv.py OUT.csv ROWS SEED
"""
import sys

import numpy as np
import pandas as pd

out, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rng = np.random.default_rng(seed)

age = rng.normal(54, 9, n).clip(29, 80).round()
sex = (rng.random(n) < 0.68).astype(int)
cp = rng.choice([1, 2, 3, 4], n, p=[0.08, 0.17, 0.28, 0.47])
trestbps = rng.normal(132 + 0.3 * (age - 54), 17, n).clip(94, 200).round()
chol = rng.normal(242, 48, n).clip(126, 564).round()
fbs = (rng.random(n) < 0.15).astype(int)
restecg = rng.choice([0, 1, 2], n, p=[0.55, 0.15, 0.30])
thalach = rng.normal(150 - 0.9 * (age - 54), 21, n).clip(71, 202).round()
exang = (rng.random(n) < 0.25 + 0.2 * (cp == 4)).astype(int)
oldpeak = rng.gamma(1.3, 0.8, n).clip(0, 6.2).round(1) * (rng.random(n) < 0.7)

z = (-1.9 + 0.045 * (age - 54) + 0.9 * sex + 1.3 * (cp == 4) - 0.4 * (cp == 2) + 0.012 * (trestbps - 132)
     + 0.004 * (chol - 242) + 0.3 * fbs - 0.025 * (thalach - 150) + 0.9 * exang + 0.55 * oldpeak)
target = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)

df = pd.DataFrame({"age": age, "sex": sex, "cp": cp, "trestbps": trestbps, "chol": chol, "fbs": fbs,
                   "restecg": restecg, "thalach": thalach, "exang": exang, "oldpeak": oldpeak, "target": target})
for col, frac in (("chol", 0.04), ("trestbps", 0.02), ("thalach", 0.02)):  # a few unmeasured values, like real records
    df.loc[rng.random(n) < frac, col] = np.nan
df = df.astype({c: "Int64" for c in ("age", "sex", "cp", "trestbps", "chol", "fbs", "restecg", "thalach", "exang", "target")})
df.to_csv(out, index=False)
print(f"{out}: {n} rows, {int(target.sum())} with heart disease ({target.mean():.0%})")
