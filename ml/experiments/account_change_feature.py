"""Research experiment R3: 'bank details changed since the pair's last payment' feature.

Same LightGBM recipe as train.py (seed A days <=20 train, days 21-25 thresholds),
with and without the extra monotone(+1) feature, model-only metrics on seeds B and C.
"""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import roc_auc_score

from sylo_risk.evaluate import _feature_frame, _load_frame
from sylo_risk.features import FEATURE_NAMES, MONOTONE_CONSTRAINTS
from sylo_risk.train import _thresholds


def account_changed(frame):
    order = np.argsort(frame["day"].to_numpy(), kind="stable")
    g = frame.iloc[order]
    prev = g.groupby(["payer_id", "payee_id"])["account_id"].shift(1)
    return (prev.notna() & (prev != g["account_id"])).reindex(frame.index).to_numpy(float)


def matrix(frame, extra):
    X = _feature_frame(frame).to_numpy(float)
    return np.column_stack([X, account_changed(frame)]) if extra else X


def fit(X, y, extra):
    mono = list(MONOTONE_CONSTRAINTS) + ([1] if extra else [])
    m = lgb.LGBMClassifier(objective="binary", n_estimators=240, learning_rate=0.05, num_leaves=15,
                           min_child_samples=35, reg_lambda=1.0, random_state=20261001, n_jobs=1,
                           deterministic=True, force_col_wise=True, monotone_constraints=mono, verbosity=-1)
    m.fit(X, y)
    return m


def metrics(frame, p, t_med, t_high):
    y = frame["label"].to_numpy(bool)
    typ = frame["typology"].astype(str).to_numpy()
    ev = frame["evasive"].fillna(False).to_numpy(bool)
    hn = frame["hard_negative"].to_numpy(bool) & ~y
    flag, high = p >= t_med, p >= t_high
    r = lambda m: round(float(flag[m].mean()) * 100, 2)
    return {"auc": round(roc_auc_score(y, p), 5), "recallAll": r(y), "recallT1": r(typ == "T1"),
            "recallT1Evasive": r((typ == "T1") & ev), "recallT2": r(typ == "T2"), "recallT3": r(typ == "T3"),
            "recallT4": r(typ == "T4"), "fprLegit": r(~y), "fprHardNeg": r(hn),
            "precisionHigh": round(float(y[high].mean()) * 100, 2) if high.any() else None}


a = _load_frame("A")
tr, va = a[a["day"] <= 20], a[a["day"].between(21, 25)]
out = {}
seeds = {s: _load_frame(s) for s in ("B", "C")}
for extra in (False, True):
    name = "with_account_changed" if extra else "baseline"
    m = fit(matrix(tr, extra), tr["label"].to_numpy(int), extra)
    pv = m.predict_proba(matrix(va, extra))[:, 1]
    t_med, t_high, *_ = _thresholds(pv, va["label"].to_numpy(int))
    out[name] = {"t_med": t_med, "t_high": t_high}
    for s, f in seeds.items():
        out[name][s] = metrics(f, m.predict_proba(matrix(f, extra))[:, 1], t_med, t_high)
    print(name, json.dumps(out[name]))
Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=2))
