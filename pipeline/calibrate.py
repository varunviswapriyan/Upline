import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from engine import Engine

e = Engine()
obs = np.array(e.m["obs_restoration_curve_ice"][:9])
days = np.arange(len(obs))


def sim_curve(crews):
    sc = {"hazard": "ice", "severity": 1.0, "crews": crews}
    r = e.region_curve(sc, n_runs=10, seed=1)
    h = np.array(r["hours"])
    jd = np.array(r["jobs_done"])
    return np.interp(days * 24, h, jd)


best = None
for crews in range(40, 301, 10):
    c = sim_curve(crews)
    err = float(np.sqrt(np.mean((c - obs) ** 2)))
    if best is None or err < best[1]:
        best = (crews, err, c)
    print(f"crews={crews:4d} rmse={err:.3f}")
crews, err, c = best
out = {"crews": crews, "rmse": round(err, 3), "days": days.tolist(),
       "observed": [round(float(x), 3) for x in obs], "simulated": [round(float(x), 3) for x in c],
       "note": "Effective crews = crews needed to reproduce the observed Feb-2025 repair-completion curve "
               "with STORMS labor hours x 4.5 ILM, 4-person crews and 16-hour shifts."}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "calibration.json"), "w"))
print("BEST", out)
