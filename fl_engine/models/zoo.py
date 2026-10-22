"""Centralised model zoo. Each `fit_*` returns a predict-probability callable.

Protocol (identical for every model): fit on the inner-train split; the inner-validation
split is used only for hyper-parameter search (same Optuna trial budget for every tuned
model), early stopping, threshold selection and calibration. The outer test fold is
never seen.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable

import numpy as np
import optuna
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from .nets import PaperMLP, TunableMLP, predict_proba, set_seed, train_torch

optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.filterwarnings("ignore", category=UserWarning)

Predictor = Callable[[np.ndarray], np.ndarray]

# Paper-style NN config: AdamW lr 0.01, wd 1e-2, large batches; epochs are chosen per
# dataset so the number of optimiser steps is of the same order (a few hundred).
PAPER_NN_EPOCHS = {"uci": 500, "cardio": 300, "cardio_lowprev": 300}


def fit_paper_lr(Xtr, ytr, Xva, yva, seed, budget, dataset) -> tuple[Predictor, dict]:
    m = LogisticRegression(solver="liblinear", random_state=seed).fit(Xtr, ytr)
    return (lambda X: m.predict_proba(X)[:, 1]), {}


def fit_paper_nn(Xtr, ytr, Xva, yva, seed, budget, dataset) -> tuple[Predictor, dict]:
    set_seed(seed)
    model = PaperMLP(Xtr.shape[1])
    train_torch(model, Xtr, ytr, epochs=PAPER_NN_EPOCHS[dataset], lr=0.01,
                batch_size=min(20000, len(Xtr)), weight_decay=1e-2, seed=seed)
    return (lambda X: predict_proba(model, X)), {}


def _search(objective, budget: int, seed: int) -> optuna.Study:
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=budget, show_progress_bar=False)
    return study


def fit_tuned_mlp(Xtr, ytr, Xva, yva, seed, budget, dataset) -> tuple[Predictor, dict]:
    models = {}

    def obj(trial):
        set_seed(seed)
        m = TunableMLP(Xtr.shape[1], hidden=trial.suggest_categorical("hidden", [8, 16, 32, 64]),
                       layers=trial.suggest_int("layers", 1, 3),
                       dropout=trial.suggest_float("dropout", 0.0, 0.5))
        train_torch(m, Xtr, ytr, epochs=200, lr=trial.suggest_float("lr", 1e-4, 3e-2, log=True),
                    batch_size=trial.suggest_categorical("batch", [64, 256, 1024]),
                    weight_decay=trial.suggest_float("wd", 1e-5, 1e-1, log=True), seed=seed,
                    X_val=Xva, y_val=yva, patience=15)
        models[trial.number] = m
        return roc_auc_score(yva, predict_proba(m, Xva))

    st = _search(obj, budget, seed)
    best = models[st.best_trial.number]
    return (lambda X: predict_proba(best, X)), st.best_params


def fit_xgb(Xtr, ytr, Xva, yva, seed, budget, dataset) -> tuple[Predictor, dict]:
    from xgboost import XGBClassifier
    models = {}

    def obj(trial):
        m = XGBClassifier(
            n_estimators=1000, early_stopping_rounds=50, eval_metric="logloss", n_jobs=1,
            random_state=seed, tree_method="hist",
            max_depth=trial.suggest_int("max_depth", 2, 8),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            subsample=trial.suggest_float("subsample", 0.5, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.5, 1.0),
            min_child_weight=trial.suggest_float("min_child_weight", 1, 20, log=True),
            reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 10, log=True),
        ).fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
        models[trial.number] = m
        return roc_auc_score(yva, m.predict_proba(Xva)[:, 1])

    st = _search(obj, budget, seed)
    best = models[st.best_trial.number]
    return (lambda X: best.predict_proba(X)[:, 1]), st.best_params


def fit_lgbm(Xtr, ytr, Xva, yva, seed, budget, dataset) -> tuple[Predictor, dict]:
    import lightgbm as lgb
    models = {}

    def obj(trial):
        m = lgb.LGBMClassifier(
            n_estimators=1000, random_state=seed, n_jobs=1, verbose=-1,
            num_leaves=trial.suggest_int("num_leaves", 4, 64, log=True),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            feature_fraction=trial.suggest_float("feature_fraction", 0.5, 1.0),
            bagging_fraction=trial.suggest_float("bagging_fraction", 0.5, 1.0), bagging_freq=1,
            min_child_samples=trial.suggest_int("min_child_samples", 5, 100, log=True),
            reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 10, log=True),
        ).fit(Xtr, ytr, eval_X=Xva, eval_y=yva, callbacks=[lgb.early_stopping(50, verbose=False)])
        models[trial.number] = m
        return roc_auc_score(yva, m.predict_proba(Xva)[:, 1])

    st = _search(obj, budget, seed)
    best = models[st.best_trial.number]
    return (lambda X: best.predict_proba(X)[:, 1]), st.best_params


def fit_rf(Xtr, ytr, Xva, yva, seed, budget, dataset) -> tuple[Predictor, dict]:
    models = {}

    def obj(trial):
        m = RandomForestClassifier(
            n_estimators=300, n_jobs=1, random_state=seed,
            max_depth=trial.suggest_categorical("max_depth", [None, 4, 8, 12, 20]),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 50, log=True),
            max_features=trial.suggest_categorical("max_features", ["sqrt", 0.5, 1.0]),
        ).fit(Xtr, ytr)
        models[trial.number] = m
        return roc_auc_score(yva, m.predict_proba(Xva)[:, 1])

    st = _search(obj, budget, seed)
    best = models[st.best_trial.number]
    return (lambda X: best.predict_proba(X)[:, 1]), st.best_params


# name -> (fit function, scaler, is_paper_reimplementation)
ZOO = {
    "paper_lr": (fit_paper_lr, "minmax", True),
    "paper_nn": (fit_paper_nn, "standard", True),
    "tuned_mlp": (fit_tuned_mlp, "standard", False),
    "xgboost": (fit_xgb, "standard", False),
    "lightgbm": (fit_lgbm, "standard", False),
    "random_forest": (fit_rf, "standard", False),
}
