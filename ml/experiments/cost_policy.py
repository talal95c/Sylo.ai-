"""Research experiment R1: amount-aware (example-dependent cost-sensitive) hold policy.

Model-only comparison at matched analyst budget. C is tuned on seed A validation
(days 21-25) and then frozen for seeds B and C. Never replaces the rules floor.
"""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from sylo_risk.evaluate import _feature_frame, _load_frame

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
art = json.loads((MODEL_DIR / "model.json").read_text())
booster = lgb.Booster(model_file=str(MODEL_DIR / art["tree_model"]))
iso_x, iso_y = np.array(art["isotonic"]["x"]), np.array(art["isotonic"]["y"])
t_med = art["thresholds"]["t_med"]


def probs(frame):
    raw = booster.predict(_feature_frame(frame).to_numpy(dtype=float), num_threads=1)
    return raw, np.interp(raw, iso_x, iso_y)


def report(name, frame, hold):
    y = frame["label"].to_numpy(bool)
    amt = frame["amount_eur"].to_numpy(float)
    typ = frame["typology"].astype(str).to_numpy()
    out = {
        "policy": name,
        "holds": int(hold.sum()),
        "fprLegit": round(float(hold[~y].mean()) * 100, 3),
        "recallCount": round(float(hold[y].mean()) * 100, 2),
        "valueStoppedPct": round(float(amt[hold & y].sum() / amt[y].sum()) * 100, 2),
        "legitEurHeld": round(float(amt[hold & ~y].sum()) / 1e6, 2),
    }
    for t in ("T1", "T2", "T3", "T4"):
        m = typ == t
        out[f"recall{t}"] = round(float(hold[m].mean()) * 100, 2)
    return out


a = _load_frame("A")
val = a[a["day"].between(21, 25)] if "day" in a.columns else a.iloc[int(len(a) * 0.8):]
raw_v, cal_v = probs(val)
amt_v = val["amount_eur"].to_numpy(float)
budget = int((raw_v >= t_med).sum())
ev_v = cal_v * amt_v
C = float(np.sort(ev_v)[::-1][budget - 1])  # matched number of holds on A-val
# hybrid: never looser than the threshold policy, extra holds by expected loss, +10% budget
extra = int(round(budget * 0.10))
ev_rest = np.sort(ev_v[raw_v < t_med])[::-1]
C_h = float(ev_rest[extra - 1])
print(json.dumps({"t_med": t_med, "budgetAval": budget, "C_eur": round(C, 2), "C_hybrid_eur": round(C_h, 2)}))

results = []
for seed in ("B", "C"):
    f = _load_frame(seed)
    raw, cal = probs(f)
    ev = cal * f["amount_eur"].to_numpy(float)
    for name, hold in (
        ("threshold t_med (current)", raw >= t_med),
        ("expected-loss p*amount>=C", ev >= C),
        ("hybrid t_med OR p*amount>=C_h", (raw >= t_med) | (ev >= C_h)),
    ):
        r = report(name, f, hold)
        r["seed"] = seed
        results.append(r)
        print(json.dumps(r))
Path(__file__).with_suffix(".json").write_text(json.dumps({"C": C, "C_h": C_h, "results": results}, indent=2))
