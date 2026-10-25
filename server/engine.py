# Calculates risk and restoration times

import heapq
import json
import math
import os
import random
import time

import numpy as np

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# risk bands
BANDS = [(0.10, "Low"), (0.30, "Elevated"), (0.60, "High"), (1.01, "Severe")]

HAZARDS = {
    "ice": {"label": "Ice storm", "start_delay": 18, "access_mult": 1.15, "assess": 4},
    "tropical": {"label": "Tropical remnants (wind + heavy rain)", "start_delay": 12, "access_mult": 1.25, "assess": 4},
    "wind": {"label": "Severe thunderstorm / wind", "start_delay": 4, "access_mult": 1.0, "assess": 2},
}

PRESETS = [
    {"id": "ice25", "label": "Ice storm (Feb 2025 class)", "hazard": "ice", "severity": 1.0,
     "note": "Severity 1.0 = the Feb 12–18 2025 ice storm in this service area (1,250 damage records)."},
    {"id": "helene", "label": "Tropical remnants (Helene class)", "hazard": "tropical", "severity": 0.14,
     "note": "Calibrated to Sep 27–30 2024 Helene damage in this area (193 records)."},
    {"id": "tstorm", "label": "Severe thunderstorm line", "hazard": "wind", "severity": 0.06,
     "note": "Assumption: a typical strong summer squall line (~6% of the Feb 2025 damage)."},
    {"id": "extreme", "label": "Extreme event (derecho / major ice)", "hazard": "ice", "severity": 2.2,
     "note": "Stress test: roughly twice the Feb 2025 damage."},
]

# converts probability into risk
def band_of(p):
    for t, name in BANDS:
        if p < t:
            return name
    return "Severe"

# converts risk label to index in BANDS
def band_index(name):
    return [b for _, b in BANDS].index(name)


class Engine:
    # load info from jsons
    def __init__(self):
        t0 = time.time()
        with open(os.path.join(DATA, "model.json")) as f:
            self.m = json.load(f)
        with open(os.path.join(DATA, "network.json")) as f:
            net = json.load(f)
        with open(os.path.join(DATA, "premises.json")) as f:
            self.p = json.load(f)
        with open(os.path.join(DATA, "map.json")) as f:
            self.map = json.load(f)
        calib_path = os.path.join(DATA, "calibration.json")
        self.calib = json.load(open(calib_path)) if os.path.exists(calib_path) else {"crews": 300}
        # set up other needed information
        zs = net["zones"]
        self.nz = len(zs)
        self.z_kind = np.array([z[0] for z in zs])
        self.z_parent = np.array([z[1] for z in zs], dtype=int)
        self.z_direct = np.array([z[2] for z in zs], dtype=float)
        self.z_down = np.array([z[3] for z in zs], dtype=float)
        self.z_eta = np.array([z[4] for z in zs], dtype=float)
        self.z_sd = np.array([z[5] for z in zs], dtype=float)
        self.z_oh_mi = np.array([z[6] for z in zs], dtype=float)
        self.z_ug_mi = np.array([z[7] for z in zs], dtype=float)
        self.z_poles = np.array([z[8] for z in zs], dtype=int)
        self.z_age = np.array([z[9] for z in zs], dtype=float)
        self.z_wood = np.array([z[10] for z in zs], dtype=float)
        self.z_topf = [z[11] for z in zs]
        self.z_topc = [z[12] for z in zs]
        self.z_crit = np.array([z[13] for z in zs], dtype=int)
        self.z_hist = np.array([z[14] for z in zs], dtype=int)
        self.z_ohf = np.array([z[15] for z in zs], dtype=float)

        x = net["xfs"]
        self.x_zi = np.array(x["zi"], dtype=int)
        self.x_n = np.array(x["n"], dtype=float)
        self.x_oh = np.array(x["oh"], dtype=int)
        self.x_steps = np.array(x["steps"], dtype=int)

        self.pid_index = {pid: i for i, pid in enumerate(self.p["pid"])}
        self.p_xi = np.array(self.p["xi"], dtype=int)

        depth = np.zeros(self.nz, dtype=int)
        for i in range(self.nz):
            d, q = 0, self.z_parent[i]
            while q >= 0 and d < 40:
                d += 1
                q = self.z_parent[q]
            depth[i] = d
        self.z_depth = depth
        self.depth_levels = [np.where(depth == d)[0] for d in range(depth.max() + 1)]

        ee = np.exp(self.z_eta)
        self.S = np.zeros(self.nz)
        self.S_hi = np.zeros(self.nz)
        self.S_lo = np.zeros(self.nz)
        for lvl in self.depth_levels:
            par = self.z_parent[lvl]
            has = par >= 0
            base = np.where(has, self.S[np.maximum(par, 0)], 0.0)
            base_hi = np.where(has, self.S_hi[np.maximum(par, 0)], 0.0)
            base_lo = np.where(has, self.S_lo[np.maximum(par, 0)], 0.0)
            self.S[lvl] = ee[lvl] + base
            self.S_hi[lvl] = np.exp(self.z_eta[lvl] + self.z_sd[lvl]) + base_hi
            self.S_lo[lvl] = np.exp(self.z_eta[lvl] - self.z_sd[lvl]) + base_lo
        self.sum_ee = ee.sum()
        self.n_ref = self.m["observed_zone_damage"]["ice_feb2025"]
        self.loc_rate = self.m["local_rate"]

        lab = self.m["labor"]
        self.ilm = lab["ilm"]
        self.crew_size = 4
        self.job_hours = {k: v["crew_hours"] / self.crew_size for k, v in lab["assemblies"].items()}
        mix = self.m["job_mix"]
        zone_classes = [c for c in mix if c not in ("secondary_wire", "transformer")]
        w = np.array([mix[c] for c in zone_classes])
        self.zone_classes = zone_classes
        self.zone_class_p = w / w.sum()
        lw = np.array([mix.get("secondary_wire", 0.6), mix.get("transformer", 0.4)])
        self.local_classes = ["secondary_wire", "transformer"]
        self.local_class_p = lw / lw.sum()
        q = self.m["qty_dist"]
        self.qty_vals = np.array([int(k) for k in q])
        self.qty_p = np.array(list(q.values()), dtype=float)
        self.qty_p /= self.qty_p.sum()
        self.access_rate = self.m["access_rate"]

        self.cells = self.map["cells"]
        self._personas = None
        self.audit = []
        print(f"[engine] loaded {len(self.pid_index):,} premises, {self.nz:,} zones in {time.time() - t0:.1f}s")

    # records events for history and debugging
    def log(self, tool, inputs, summary):
        self.audit.append({"t": time.strftime("%H:%M:%S"), "tool": tool, "inputs": inputs, "out": summary})
        self.audit = self.audit[-300:]
    # get the scenario/the details of the storm
    def scenario(self, sc):
        sc = sc or {}
        hz = sc.get("hazard", "ice")
        if hz not in HAZARDS:
            hz = "ice"
        s = float(sc.get("severity", 1.0))
        s = min(max(s, 0.01), 3.0)
        return {
            "hazard": hz, "severity": s,
            "forecast_uncertainty": float(sc.get("forecast_uncertainty", 0.35)),
            "crew_pct": float(sc.get("crew_pct", 100)),
            "crews": int(sc["crews"]) if "crews" in sc else max(1, int(round(self.calib.get("crews", 300) * float(sc.get("crew_pct", 100)) / 100))),
            "mutual_aid": int(sc["mutual_aid"]) if "mutual_aid" in sc else int(round(self.calib.get("crews", 300) * float(sc.get("mutual_aid_pct", 0)) / 100)),
            "mutual_aid_pct": float(sc.get("mutual_aid_pct", 0)),
            "mutual_aid_hours": float(sc.get("mutual_aid_hours", 36)),
            "access_pct": float(sc.get("access_pct", round(self.access_rate * HAZARDS[hz]["access_mult"] * 100))),
            "extra_damage": float(sc.get("extra_damage", 1.0)),
            "hours_to_storm": float(sc.get("hours_to_storm", 24)),
            "source": sc.get("source", "preset"),
        }

    def intercept(self, s):
        return math.log(s * self.n_ref / self.sum_ee)

    def local_lambda(self, xi, s):
        r = self.loc_rate["oh"] if self.x_oh[xi] else self.loc_rate["ug"]
        return -math.log(1 - min(r, 0.5)) * s

    # get path to the house
    def path(self, zi):
        out = []
        z = zi
        while z >= 0 and len(out) < 40:
            out.append(int(z))
            z = int(self.z_parent[z])
        return out

    def find(self, pid):
        if pid is None:
            return None
        pid = str(pid).strip().upper()
        if not pid.startswith("UPL-"):
            pid = "UPL-" + pid
        return self.pid_index.get(pid)

    def device_label(self, z, k):
        kind = {"f": "Fuse", "r": "Recloser", "s": "Sectionalizer", "b": "Substation breaker"}[self.z_kind[z]]
        return kind

    # calculate outage probability from network risk
    def premise_prob(self, xi, s, eta_shift="mid"):
        a = self.intercept(s)
        zi = self.x_zi[xi]
        S = {"mid": self.S, "hi": self.S_hi, "lo": self.S_lo}[eta_shift][zi]
        lam = math.exp(a) * S + self.local_lambda(xi, s)
        return 1 - math.exp(-lam), lam
    # estimates risk and creates explanation of risk
    def risk(self, pid, sc):
        sc = self.scenario(sc)
        i = self.find(pid)
        if i is None:
            return {"ok": False, "fallback": True,
                    "message": "We couldn't match that location to the network data, so we can't make a reliable "
                               "prediction. Please prepare as if an outage is possible and follow official alerts."}
        xi = int(self.p_xi[i])
        s = sc["severity"]
        fu = sc["forecast_uncertainty"]
        p, lam = self.premise_prob(xi, s)
        p_lo, _ = self.premise_prob(xi, s * (1 - fu), "lo")
        p_hi, _ = self.premise_prob(xi, min(3.0, s * (1 + fu)), "hi")
        b, blo, bhi = band_of(p), band_of(p_lo), band_of(p_hi)
        spread = band_index(bhi) - band_index(blo)
        zi = int(self.x_zi[xi])
        pth = self.path(zi)
        a = self.intercept(s)
        local = self.local_lambda(xi, s)
        lam_z = [math.exp(self.z_eta[z] + a) for z in pth]
        tot = sum(lam_z) + local
        support = sum(self.z_direct[z] for z in pth)
        rel_sd = float(np.mean([self.z_sd[z] for z in pth]))
        if spread == 0 and rel_sd < 0.35:
            conf = "High"
        elif spread <= 1:
            conf = "Medium"
        else:
            conf = "Low"
        reliable = support >= 10 and rel_sd < 0.9
        if not reliable:
            conf = "Low"

        counters = {"f": 0, "r": 0, "s": 0, "b": 0}
        svc = self.p["svc"][i]
        nodes = [{"kind": "home", "label": "Your home",
                  "detail": ("Overhead service drop" if svc == "O" else
                             "Underground service" if svc == "U" else "Service type unknown"),
                  "friendly": "Your home",
                  "fdetail": ("Wire from the pole to your house" if svc == "O" else
                              "Buried wire to your house" if svc == "U" else "Connection to your house"),
                  "share": round(local / tot, 3)}]
        nx = int(self.x_n[xi])
        nodes.append({"kind": "transformer", "label": "Neighborhood transformer",
                      "detail": f"Shared with about {nx} home{'s' if nx != 1 else ''}",
                      "friendly": "Your transformer",
                      "fdetail": f"The can or box that serves you and {max(nx - 1, 0)} neighbor{'s' if nx - 1 != 1 else ''}",
                      "share": None})
        if self.x_steps[xi]:
            nodes.append({"kind": "step", "label": "Step-down transformer", "detail": "Voltage step on this branch",
                          "friendly": "Voltage step-down", "fdetail": "Lowers the voltage for your area",
                          "share": None})
        n_fuse_total = sum(1 for z in pth if self.z_kind[z] == "f")
        n_rec_total = sum(1 for z in pth if self.z_kind[z] in "rs")
        for z, lz in zip(pth, lam_z):
            k = self.z_kind[z]
            counters[k] += 1
            name = {"f": "Fuse", "r": "Recloser", "s": "Sectionalizer", "b": "Substation breaker"}[k]
            if k != "b":
                name += f" {counters[k]}"
            down = int(self.z_down[z])
            detail = (f"Protects ~{_round_people(down)} homes · {self.z_oh_mi[z]:.1f} mi overhead"
                      f"{f', {self.z_ug_mi[z]:.1f} mi underground' if self.z_ug_mi[z] >= 0.05 else ''}"
                      f" · {self.z_poles[z]} poles")
            oh = self.z_oh_mi[z]
            wire = (f"{oh:.1f} miles of overhead wire" if oh >= 0.1 else "mostly underground or very short")
            if k == "b":
                fr = "Main line from the substation"
            elif k in "rs":
                fr = "Branch line" + (f" {counters['r'] + counters['s']}" if n_rec_total > 1 else "")
            else:
                fr = "Your street's line" if counters["f"] == 1 else "Neighborhood line"
            fdetail = f"Feeds about {_round_people(down)} homes · {wire}"
            nodes.append({"kind": {"f": "fuse", "r": "recloser", "s": "sectionalizer", "b": "breaker"}[k],
                          "label": name, "detail": detail, "friendly": fr, "fdetail": fdetail,
                          "share": round(lz / tot, 3),
                          "zone_p": round(1 - math.exp(-lz), 3), "history": int(self.z_hist[z]),
                          "down": down})

        top_i = int(np.argmax(lam_z)) if lam_z else 0
        zt = pth[top_i]
        feats = self.m["features"]
        fr = self.m["friendly"]
        drivers = []
        for f_idx, c in zip(self.z_topf[zt], self.z_topc[zt]):
            if c > 0.02:
                drivers.append({"factor": fr[feats[f_idx]], "effect": "raises risk", "weight": round(c, 2)})
        total_oh = sum(self.z_oh_mi[z] for z in pth)
        hist = int(sum(self.z_hist[z] for z in pth))
        factors = [
            {"label": "Overhead line upstream of you", "value": f"{total_oh:.1f} miles", "effect": "up" if total_oh > 3 else "neutral",
             "why": "Most storm damage happens to overhead wires and poles hit by ice-laden or falling trees."},
            {"label": "Protective devices between you and the substation", "value": str(len(pth)),
             "effect": "neutral",
             "why": "Damage inside any of these sections can take your power out; damage elsewhere usually can't."},
            {"label": "Riskiest section on your path", "value": nodes[top_i + 2 + (1 if self.x_steps[xi] else 0)]["label"],
             "effect": "up", "why": f"It accounts for {lam_z[top_i] / tot:.0%} of your total risk."},
            {"label": "Your service connection", "value": nodes[0]["detail"],
             "effect": "up" if self.p["svc"][i] == "O" else "down",
             "why": "Overhead drops can be pulled down by limbs; underground service is more sheltered."},
            {"label": "Past damage recorded on your path (2022–2026)", "value": str(hist), "effect": "up" if hist > 3 else "neutral",
             "why": "Historical damage in these sections (anonymized utility records)."},
        ]
        res = {
            "ok": True, "pid": self.p["pid"][i], "city": self.p["city"][i],
            "probability": round(p, 3), "range": [round(p_lo, 3), round(p_hi, 3)],
            "band": b, "band_range": [blo, bhi], "confidence": conf, "reliable": reliable,
            "scenario": sc, "path": nodes, "drivers": drivers, "factors": factors,
            "expected_regional_damage": round(s * self.n_ref * sc["extra_damage"]),
            "assumptions": [
                f"Storm severity {s:.2f}× the Feb 2025 ice storm in this service area (±{fu:.0%} forecast uncertainty).",
                "Outage = sustained damage in a protective section on your path, or on your transformer/service.",
                "Transmission and substation failures are not modeled (not in the data package).",
                "Vegetation and real-time weather by street are not available; rural density is a proxy for tree exposure.",
            ],
            "could_change": [
                "A stronger or weaker storm than forecast (move the severity slider).",
                "Tree trimming or recent line upgrades not reflected in the data.",
                "Local wind/ice bands that hit your area harder than the regional average.",
            ],
        }
        if not reliable:
            res["fallback_message"] = ("Our model has limited data for your part of the network, so treat this as a "
                                       "rough guide only. Prepare for a possible outage and follow official alerts.")
        self.log("get_outage_risk", {"pid": res["pid"], "severity": s, "hazard": sc["hazard"]},
                 f"{b} ({p:.0%}), confidence {conf}")
        return res

    # calculates outage information for the map
    def map_layer(self, sc):
        sc = self.scenario(sc)
        a = self.intercept(sc["severity"])
        r = np.where(self.x_oh == 1, self.loc_rate["oh"], self.loc_rate["ug"])
        lam = math.exp(a) * self.S[self.x_zi] - np.log(1 - np.minimum(r, 0.5)) * sc["severity"]
        px = 1 - np.exp(-lam)
        pp = px[self.p_xi]
        gx = np.array(self.p["gx"])
        gy = np.array(self.p["gy"])
        key = gx.astype(np.int64) * 100000 + gy
        uniq, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        sums = np.bincount(inv, weights=pp)
        k = self.m["k_anon"]
        cells = []
        for u, c, sm in zip(uniq, cnt, sums):
            if c >= k:
                cells.append([int(u // 100000), int(u % 100000), int(c), round(float(sm / c), 3)])
        expected_out = float(pp.sum())
        return {"cells": cells, "grid": self.m["grid"], "expected_customers_out": round(expected_out),
                "customers": int(len(pp)), "suppressed_cells": int((cnt < k).sum())}

    # runs many simulations and calculates restoration times
    def _simulate(self, sc, rng, force_xi=None, n_runs=150, track_region=False, extra_jobs=None):
        s = sc["severity"] * sc["extra_damage"]
        hz = HAZARDS[sc["hazard"]]
        a = self.intercept(s)
        lam_z = np.exp(self.z_eta + a)
        lam_loc = -np.log(1 - np.minimum(np.where(self.x_oh == 1, self.loc_rate["oh"], self.loc_rate["ug"]), 0.5)) * s
        crews = max(1, sc["crews"])
        aid = max(0, sc["mutual_aid"])
        aid_t = sc["mutual_aid_hours"]
        acc_p = min(max(sc["access_pct"] / 100.0, 0), 1)
        start = hz["start_delay"] + hz["assess"]
        shift = 24.0 / 16.0
        adder_access = (self.m["labor"]["adders"]["access_restricted"] + self.m["labor"]["adders"]["confined_backyard"]) * self.ilm / self.crew_size
        prio_boost = 1 + 4 * self.z_crit

        target_path = None
        if force_xi is not None:
            target_path = self.path(int(self.x_zi[force_xi]))
            w = np.r_[lam_z[target_path], lam_loc[force_xi]]
            w = w / w.sum()

        results = []
        region_curves = []
        jobs_count = []
        for run in range(n_runs):
            nz = rng.poisson(lam_z)
            nloc = rng.random(len(lam_loc)) < (1 - np.exp(-lam_loc))
            forced_local = False
            if target_path is not None:
                on_path = nz[target_path].sum() > 0 or nloc[force_xi]
                if not on_path:
                    k = rng.choice(len(w), p=w)
                    if k == len(target_path):
                        nloc[force_xi] = True
                        forced_local = True
                    else:
                        nz[target_path[k]] += 1
            zone_ids = np.repeat(np.arange(self.nz), nz)
            loc_ids = np.where(nloc)[0]
            cls_z = rng.choice(len(self.zone_classes), size=len(zone_ids), p=self.zone_class_p)
            cls_l = rng.choice(2, size=len(loc_ids), p=self.local_class_p)
            if extra_jobs:
                for ej in extra_jobs:
                    if ej.get("zone") is not None:
                        zone_ids = np.r_[zone_ids, ej["zone"]]
                        cls_z = np.r_[cls_z, self.zone_classes.index(ej.get("cls", "primary_wire"))]
                    elif ej.get("local") is not None and ej["local"] not in set(loc_ids.tolist()):
                        loc_ids = np.r_[loc_ids, ej["local"]]
                        cls_l = np.r_[cls_l, self.local_classes.index(ej.get("cls", "secondary_wire"))]
            nj_z, nj_l = len(zone_ids), len(loc_ids)
            hz_z = np.array([self.job_hours[self.zone_classes[c]] for c in cls_z]) if nj_z else np.zeros(0)
            hz_l = np.array([self.job_hours[self.local_classes[c]] for c in cls_l]) if nj_l else np.zeros(0)
            hours = np.r_[hz_z, hz_l]
            qty = rng.choice(self.qty_vals, size=len(hours), p=self.qty_p)
            hours = hours * (1 + 0.6 * (qty - 1))
            acc = rng.random(len(hours)) < acc_p
            hours = hours + acc * adder_access
            hours = hours * rng.lognormal(0, 0.3, len(hours))
            cust = np.r_[self.z_down[zone_ids] * prio_boost[zone_ids], self.x_n[loc_ids]]
            prio = cust / hours
            order = np.argsort(-prio)
            free = [start] * crews
            heapq.heapify(free)
            finish = np.zeros(len(hours))
            aid_added = False
            for j in order:
                if aid and not aid_added and free[0] >= aid_t:
                    for _ in range(aid):
                        heapq.heappush(free, max(aid_t, start))
                    aid_added = True
                t0 = heapq.heappop(free)
                t1 = t0 + hours[j] * shift
                finish[j] = t1
                heapq.heappush(free, t1)
            own = np.zeros(self.nz)
            if nj_z:
                np.maximum.at(own, zone_ids, finish[:nj_z])
            E = own.copy()
            dmg = np.zeros(self.nz, dtype=bool)
            dmg[zone_ids] = True
            out = dmg.copy()
            if len(loc_ids):
                nloc = nloc.copy()
                nloc[loc_ids] = True
            for lvl in self.depth_levels[1:]:
                par = self.z_parent[lvl]
                E[lvl] = np.maximum(E[lvl], E[par])
                out[lvl] = out[lvl] | out[par]
            loc_fin = np.zeros(len(self.x_n))
            if nj_l:
                loc_fin[loc_ids] = finish[nj_z:]
            if force_xi is not None:
                zi = self.x_zi[force_xi]
                t = max(E[zi], loc_fin[force_xi])
                results.append(t)
            jobs_count.append(len(hours))
            if track_region:
                x_out = out[self.x_zi] | nloc
                x_t = np.maximum(E[self.x_zi], loc_fin)
                region_curves.append((x_t[x_out], self.x_n[x_out], finish))
        return np.array(results), region_curves, jobs_count

    # turns simulation results into an estimate
    def restoration(self, pid, sc, n_runs=160, seed=11, with_drivers=True, extra_jobs=None):
        sc = self.scenario(sc)
        i = self.find(pid)
        if i is None:
            return {"ok": False, "fallback": True,
                    "message": "We can't estimate restoration for this location. Follow official utility updates."}
        xi = int(self.p_xi[i])
        rng = np.random.default_rng(seed)
        T, _, jc = self._simulate(sc, rng, force_xi=xi, n_runs=n_runs, extra_jobs=extra_jobs)
        p10, p50, p90 = [float(np.percentile(T, q)) for q in (10, 50, 90)]
        hist_edges = np.linspace(0, max(np.percentile(T, 97), 12), 25)
        hist, _ = np.histogram(T, bins=hist_edges)
        drivers = []
        if with_drivers:
            levers = [
                ("crews", "Crew capacity ±30%", lambda c: {**c, "crews": int(c["crews"] * 0.7)},
                 lambda c: {**c, "crews": int(c["crews"] * 1.3)}),
                ("severity", "Storm severity ±35%", lambda c: {**c, "severity": c["severity"] * 1.35},
                 lambda c: {**c, "severity": c["severity"] * 0.65}),
                ("access", "Blocked roads / backyard access", lambda c: {**c, "access_pct": min(100, c["access_pct"] + 30)},
                 lambda c: {**c, "access_pct": max(0, c["access_pct"] - 20)}),
                ("aid", "Mutual-aid crews (+50% at 24 h)", lambda c: {**c, "mutual_aid": 0},
                 lambda c: {**c, "mutual_aid": int(c["crews"] * 0.5), "mutual_aid_hours": 24}),
            ]
            base60, _, _ = self._simulate(sc, np.random.default_rng(seed), force_xi=xi, n_runs=60)
            b50 = float(np.percentile(base60, 50))
            for key, label, worse, better in levers:
                tw, _, _ = self._simulate(worse(sc), np.random.default_rng(seed), force_xi=xi, n_runs=60)
                tb, _, _ = self._simulate(better(sc), np.random.default_rng(seed), force_xi=xi, n_runs=60)
                drivers.append({"key": key, "label": label,
                                "worse": round(float(np.percentile(tw, 50)) - b50, 1),
                                "better": round(float(np.percentile(tb, 50)) - b50, 1)})
            drivers.sort(key=lambda d: -(abs(d["worse"]) + abs(d["better"])))
        hz = HAZARDS[sc["hazard"]]
        conf = "Medium"
        width = (p90 - p10) / max(p50, 1)
        if width < 1.0:
            conf = "High"
        elif width > 2.5:
            conf = "Low"
        res = {
            "ok": True, "pid": self.p["pid"][i], "scenario": sc,
            "p10": round(p10, 1), "p50": round(p50, 1), "p90": round(p90, 1),
            "hist": hist.tolist(), "edges": [round(e, 1) for e in hist_edges.tolist()],
            "confidence": conf, "drivers": drivers,
            "regional_jobs": int(np.median(jc)),
            "work_starts_after_h": hz["start_delay"] + hz["assess"],
            "label": "MODEL ESTIMATE — not a confirmed utility restoration time",
            "method": [
                f"{n_runs} simulated storms, each conditioned on your home losing power.",
                f"Damage sampled per protective section from the risk model (~{int(np.median(jc)):,} repair jobs region-wide).",
                "Job durations from STORMS labor-hour averages × 4.5 indirect labor multiplier (travel, setup, safety), "
                "worked by 4-person crews.",
                f"{round(sc['access_pct'])}% of jobs carry restricted-access / backyard adders (observed ~32%).",
                f"Crew capacity {sc['crew_pct']:.0f}% of the level that reproduces the observed Feb 2025 repair curve "
                f"(≈{sc['crews']} four-person crews), 16-hour shifts.",
                "Step restoration: crews prioritise repairs that bring the most customers back per hour; "
                "critical-facility sections are boosted; a section is energised only after everything upstream.",
                f"Crews begin ~{hz['start_delay'] + hz['assess']} h after the storm starts (storm passage + damage assessment).",
            ],
        }
        self.log("simulate_restoration", {"pid": res["pid"], "crews": sc["crews"], "severity": sc["severity"],
                                          "access_pct": sc["access_pct"], "mutual_aid": sc["mutual_aid"]},
                 f"P10 {p10:.0f}h · P50 {p50:.0f}h · P90 {p90:.0f}h")
        return res
    # simulates restoration and returns a simulated timeline
    def region_curve(self, sc, n_runs=12, seed=3):
        sc = self.scenario(sc)
        rng = np.random.default_rng(seed)
        _, curves, jc = self._simulate(sc, rng, n_runs=n_runs, track_region=True)
        hours = np.arange(0, 24 * 10 + 1, 6)
        cust_frac = []
        job_frac = []
        for t, n, fin in curves:
            tot = n.sum()
            cust_frac.append([float(n[t <= h].sum() / tot) if tot else 1.0 for h in hours])
            job_frac.append([float((fin <= h).mean()) if len(fin) else 1.0 for h in hours])
        cust_out = float(np.median([n.sum() for _, n, _ in curves]))
        return {"hours": hours.tolist(), "customers_restored": np.median(cust_frac, axis=0).round(3).tolist(),
                "jobs_done": np.median(job_frac, axis=0).round(3).tolist(),
                "customers_out": round(cust_out), "jobs": int(np.median(jc))}
    # calculate sample representative homes
    def personas(self):
        if self._personas:
            return self._personas
        sc = {"hazard": "ice", "severity": 1.0}
        a = self.intercept(1.0)
        r = np.where(self.x_oh == 1, self.loc_rate["oh"], self.loc_rate["ug"])
        px = 1 - np.exp(-(math.exp(a) * self.S[self.x_zi] - np.log(1 - r)))
        pp = px[self.p_xi]
        city = np.array(self.p["city"])
        svc = np.array(self.p["svc"])
        rng = np.random.default_rng(5)
        picks = []

        def pick(mask, target, label, story):
            idx = np.where(mask)[0]
            if not len(idx):
                return
            j = idx[np.argmin(np.abs(pp[idx] - target) + rng.random(len(idx)) * 0.01)]
            picks.append({"pid": self.p["pid"][j], "label": label, "city": self.p["city"][j], "story": story,
                          "svc": str(svc[j])})

        pick((city != "Roanoke") & (svc == "O"), 0.75, "Rural ridge home",
             "Long overhead feeder through wooded hills")
        pick((city == "Vinton") & (svc == "O"), 0.35, "Suburban family",
             "Overhead service, mid-length branch")
        pick((city == "Roanoke") & (svc == "U"), 0.08, "City townhouse",
             "Underground service near the substation")
        self._personas = picks
        return picks
    # random home selection based on map cell or over whole map
    def random_pid(self, cell=None):
        if cell:
            gx, gy = cell
            idx = [i for i, (a, b) in enumerate(zip(self.p["gx"], self.p["gy"])) if a == gx and b == gy]
            if idx:
                return self.p["pid"][random.choice(idx)]
        return random.choice(self.p["pid"])
    # simulates which other homes affected by possible failure along path
    def neighbors_inference(self, pid, sc, seed=4):
        i = self.find(pid)
        xi = int(self.p_xi[i])
        pth = self.path(int(self.x_zi[xi]))
        rng = np.random.default_rng(seed)
        a = self.intercept(self.scenario(sc)["severity"])
        w = np.exp(self.z_eta[pth] + a)
        k = int(rng.choice(len(pth), p=w / w.sum()))
        failed = pth[k]
        below = np.zeros(self.nz, dtype=bool)
        below[failed] = True
        for lvl in self.depth_levels[1:]:
            par = self.z_parent[lvl]
            below[lvl] |= below[par]
        xs = np.where(below[self.x_zi])[0]
        n_aff = int(self.x_n[xs].sum())
        n_reports = int(min(max(3, n_aff * 0.04), 60))
        return {"failed_index": k, "affected_homes": n_aff, "reports": n_reports,
                "device": ["Fuse", "Recloser", "Sectionalizer", "Substation breaker"][
                    "frsb".index(self.z_kind[failed])], "zone": int(failed)}


def _round_people(n):
    if n < 20:
        return str(int(n))
    if n < 1000:
        return str(int(round(n, -1)))
    return f"{n / 1000:.1f}k"
