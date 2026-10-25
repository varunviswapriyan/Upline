#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# set this folder as the root
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "server"))

# make sure we have needed data
if not os.path.exists(os.path.join(ROOT, "data", "network.json")):
    print("\n[upline] Model data not found. Build it first:\n"
          "    python pipeline/build_data.py --raw <path-to>/aep_challenge_hack26-main/data\n"
          "    python pipeline/calibrate.py\n")
    sys.exit(1)

import guidance
from concierge import Concierge
from engine import HAZARDS, PRESETS, Engine
from notify import Notifier

# create a new engine, concierge, and notifier
E = Engine()
C = Concierge(E, guidance)
N = Notifier()
LOCK = threading.Lock()
WEB = os.path.join(ROOT, "web")

# get ip
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


_TOWNS = None

# get a list of towns
def towns():
    global _TOWNS
    if _TOWNS is None:
        import collections
        acc = collections.defaultdict(lambda: [0, 0.0, 0.0])
        G = E.m["grid"]
        for c, gx, gy in zip(E.p["city"], E.p["gx"], E.p["gy"]):
            a = acc[c]
            a[0] += 1
            a[1] += gx * G
            a[2] += gy * G
        _TOWNS = sorted([[c, round(a[1] / a[0], 4), round(a[2] / a[0], 4), a[0]] for c, a in acc.items() if a[0] >= 600],
                        key=lambda t: -t[3])
    return _TOWNS

# send some data to the caller
def api_meta(_):
    m = E.m
    return {
        "personas": E.personas(), "presets": PRESETS,
        "hazards": {k: v["label"] for k, v in HAZARDS.items()},
        "map": {"backbone": E.map["backbone"], "facilities": E.map["facilities"], "grid": m["grid"], "towns": towns()},
        "model": {
            "backtests": m["backtests"], "coef": m["coef"], "friendly": m["friendly"],
            "excluded_features": m.get("excluded_features", {}), "data_notes": m["data_notes"],
            "observed_records": m["observed_records"], "labor": m["labor"], "job_mix": m["job_mix"],
            "access_rate": m["access_rate"], "calibration": E.calib, "k_anon": m["k_anon"],
            "local_rate": m["local_rate"],
        },
        "rules": guidance.RULES, "llm": C.llm_enabled, "channels": N.status(), "lan": f"http://{lan_ip()}:{PORT}",
    }

# calculate the risk and prepare guidance
def assess(body):
    # get the house, scenario, and needs of body
    pid, sc, needs = body.get("pid"), body.get("scenario", {}), body.get("needs", {}) or {}
    lang = body.get("lang", "en")
    # calculate risk using engine
    risk = E.risk(pid, sc)
    if not risk.get("ok"):
        return {"risk": risk}
    # get restoration and scenario data
    rest = E.restoration(pid, sc)
    scn = E.scenario(sc)
    # get guidance for risk, restoration, scenario
    prep = guidance.prep(risk, rest, needs, scn["hazard"], scn)
    prep["summary"], prep["summary_ai"] = C.rephrase_summary(prep["summary"], prep, risk, rest, needs)
    al = guidance.alerts(risk, rest, needs, scn, body.get("prefs"))
    msgs = guidance.messages(risk, rest, needs, scn, lang)
    # log results
    E.log("prep_plan", {"pid": pid, "needs": sorted(k for k, v in needs.items() if v)}, f"{len(prep['items'])} actions")
    E.log("check_alerts", {"pid": pid}, f"pre-storm eligible={al['eligible_pre_storm']}")
    i = E.find(pid)
    cell = [E.p["gx"][i], E.p["gy"][i]]
    return {"risk": risk, "restoration": rest, "prep": prep, "alerts": al, "messages": msgs, "cell": cell}

# Recalculate restoration times when parameters change
def api_restoration(body):
    pid, sc, needs = body.get("pid"), body.get("scenario", {}), body.get("needs", {}) or {}
    extra = _extra_from_reports(pid, body.get("reports", []))
    rest = E.restoration(pid, sc, extra_jobs=extra)
    risk = E.risk(pid, sc)
    scn = E.scenario(sc)
    return {"restoration": rest, "prep": guidance.prep(risk, rest, needs, scn["hazard"], scn),
            "alerts": guidance.alerts(risk, rest, needs, scn, body.get("prefs")),
            "messages": guidance.messages(risk, rest, needs, scn, body.get("lang", "en"))}

# holds what damages can be reported
REPORT_CLASS = {"pole": "pole", "wire": "primary_wire", "tree": "primary_wire", "transformer": "transformer",
                "service": "secondary_wire", "fuse": "fuse"}

# creates a list of user reports for damages for the model
def _extra_from_reports(pid, reports):
    i = E.find(pid)
    if i is None or not reports:
        return None
    xi = int(E.p_xi[i])
    zi = int(E.x_zi[xi])
    out = []
    for r in reports:
        cls = REPORT_CLASS.get(r, "primary_wire")
        if cls in ("transformer", "secondary_wire"):
            out.append({"local": xi, "cls": cls})
        else:
            out.append({"zone": zi, "cls": cls})
    return out

# Calculates how much an estimate changes due to a report
def api_report(body):
    pid, sc, needs = body.get("pid"), body.get("scenario", {}), body.get("needs", {}) or {}
    # get reports
    reports = body.get("reports", [])
    # calculate estimates before and after reports
    before = E.restoration(pid, sc, with_drivers=False)
    after = E.restoration(pid, sc, extra_jobs=_extra_from_reports(pid, reports), with_drivers=False)
    # descriptions of what each report type entails
    labels = {"pole": "a broken pole", "wire": "a downed wire", "tree": "a tree on the line",
              "transformer": "a damaged transformer", "service": "a pulled-down service line", "fuse": "a blown fuse"}
    what = ", ".join(labels.get(r, r) for r in reports)
    after["why_text"] = f"Reason: a customer report of {what} near your home was added to the repair plan. "
    # get the risk and the scenario
    risk = E.risk(pid, sc)
    scn = E.scenario(sc)
    msgs = guidance.messages(risk, before, needs, scn, body.get("lang", "en"), updated=after)
    # log report
    E.log("customer_damage_report", {"pid": pid, "reports": reports},
          f"P50 {before['p50']:.0f}h → {after['p50']:.0f}h")
    return {"before": before, "after": after, "message": [m for m in msgs if m["type"] == "estimate_updated"][0]}

# create a simulated outage timeline
def api_playback(body):
    pid, sc, needs = body.get("pid"), body.get("scenario", {}), body.get("needs", {}) or {}
    lang = body.get("lang", "en")
    scn = E.scenario(sc)
    risk = E.risk(pid, sc)
    rest1 = E.restoration(pid, sc, with_drivers=False)
    inf = E.neighbors_inference(pid, sc)
    friendly = {"Substation breaker": "the main line from the substation", "Recloser": "your branch line",
                "Sectionalizer": "your branch line", "Fuse": "your street's line"}.get(inf["device"], "a nearby line")
    reason = f"damage on {friendly}, which serves about {inf['affected_homes']:,} homes"
    i = E.find(pid)
    xi = int(E.p_xi[i])
    zone = inf["zone"]
    extra = [{"zone": zone, "cls": "pole"}, {"zone": zone, "cls": "primary_wire"}]
    sc2 = {**sc, "access_pct": min(100, scn["access_pct"] + 25)}
    rest2 = E.restoration(pid, sc2, extra_jobs=extra, with_drivers=False)
    rest2["why_text"] = ("Reason: crews found a broken pole and downed wire on your branch, and a blocked road "
                         "slows access. ")
    msgs = guidance.messages(risk, rest1, needs, scn, lang, updated=rest2, live={"reason": reason})
    restored_at = rest2["p50"]
    steps = [
        {"t": -scn["hours_to_storm"], "phase": "Pre-storm", "lane": "estimate",
         "title": f"Forecast: {HAZARDS[scn['hazard']]['label'].lower()} in ~{int(scn['hours_to_storm'])} h",
         "detail": f"Outage risk {risk['band']} ({risk['probability']:.0%}).", "message": msgs[0]},
        {"t": 2, "phase": "Outage confirmed", "lane": "confirmed",
         "title": f"{inf['reports']} neighbors reported outages",
         "detail": (f"Upline matched the reports to the network: the common upstream device is a "
                    f"{inf['device'].lower()} protecting ~{inf['affected_homes']:,} homes. "
                    "(Simulated utility confirmation.)"),
         "message": msgs[1], "path_index": inf["failed_index"]},
        {"t": scn["hours_to_storm"] * 0 + HAZARDS[scn["hazard"]]["start_delay"] + 6, "phase": "Estimate updated",
         "lane": "confirmed", "title": "Crew assessment: broken pole + downed wire, road blocked",
         "detail": f"Typical-case estimate moved from {guidance.fmt_h(rest1['p50'])} to {guidance.fmt_h(rest2['p50'])} "
                   "(trigger E2: change > 2 h).", "message": msgs[2]},
        {"t": restored_at, "phase": "Restored", "lane": "confirmed", "title": "Power restored",
         "detail": "Section re-energized after upstream repairs; 'still out?' check scheduled in 30 min.",
         "message": msgs[3]},
    ]
    E.log("storm_playback", {"pid": pid}, f"{len(steps)} timeline steps")
    return {"steps": steps, "before": rest1, "after": rest2, "inference": inf}

# extract needs from a household
def api_needs(body):
    from concierge import extract_needs, redact
    found = extract_needs(redact(body.get("text", "")))
    return {"needs": found, "labels": guidance.need_labels({**found, "household": 0})[:-1] if found else []}

# sends alerts
def api_send(body):
    ch = body.get("channel")
    items = [{"title": str(m.get("title", ""))[:80], "text": str(m.get("text", ""))[:1500]} for m in body.get("messages", [])][:4]
    if not items:
        return {"ok": False, "error": "no messages"}
    res = N.send(ch, body.get("to", ""), items)
    E.log("send_alert", {"channel": ch, "to": res.get("to", "invalid"), "messages": len(items)},
          "sent" if res.get("ok") else f"not sent: {res.get('error')}")
    return res

# sends question to C and returns reply
def api_chat(body):
    return C.reply(body.get("message", ""), body.get("pid"), body.get("scenario", {}), body.get("needs", {}),
                   body.get("lang", "en"))


ROUTES_POST = {
    "/api/assess": assess,
    "/api/restoration": api_restoration,
    "/api/map": lambda b: E.map_layer(b.get("scenario", {})),
    "/api/region": lambda b: E.region_curve(b.get("scenario", {})),
    "/api/chat": api_chat,
    "/api/needs": api_needs,
    "/api/send": api_send,
    "/api/report": api_report,
    "/api/playback": api_playback,
}

# Web server behavior
class H(BaseHTTPRequestHandler):
    server_version = "Upline/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=_np).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # handle http GET requests
    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/meta":
                return self._send(200, api_meta(None))
            if u.path == "/api/audit":
                return self._send(200, {"events": E.audit[::-1]})
            if u.path == "/api/random":
                q = parse_qs(u.query)
                cell = None
                if "cell" in q:
                    a, b = q["cell"][0].split(",")
                    cell = (int(a), int(b))
                return self._send(200, {"pid": E.random_pid(cell)})
            path = u.path if u.path != "/" else "/index.html"
            f = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
            if not f.startswith(WEB) or not os.path.isfile(f):
                return self._send(404, {"error": "not found"})
            ext = os.path.splitext(f)[1].lower()
            ctype = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                     ".html": "text/html; charset=utf-8", ".json": "application/manifest+json" if f.endswith("manifest.json") else "application/json",
                     ".svg": "image/svg+xml", ".png": "image/png"}.get(ext) or mimetypes.guess_type(f)[0] or "application/octet-stream"
            with open(f, "rb") as fh:
                return self._send(200, fh.read(), ctype)
        except Exception as ex:
            traceback.print_exc()
            return self._send(500, {"error": str(ex)})

    # handle HTTP POST requests
    def do_POST(self):
        u = urlparse(self.path)
        fn = ROUTES_POST.get(u.path)
        if not fn:
            return self._send(404, {"error": "unknown endpoint"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            t0 = time.time()
            with LOCK:
                out = fn(body)
            if isinstance(out, dict):
                out["_ms"] = int((time.time() - t0) * 1000)
            return self._send(200, out)
        except Exception as ex:
            traceback.print_exc()
            return self._send(500, {"error": str(ex)})


def _np(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--check-ai", action="store_true", help="test the AI connection and exit")
    a = ap.parse_args()
    # set up AI
    if a.check_ai:
        if not C.llm_enabled:
            print("AI is OFF: set UPLINE_LLM_BASE_URL, UPLINE_LLM_API_KEY and UPLINE_LLM_MODEL first.")
            sys.exit(1)
        try:
            out = C.chat_completion({"model": C.model, "max_tokens": 20,
                                     "messages": [{"role": "user", "content": "Reply with: Upline AI is working."}]})
            print(f"AI OK ({C.model}): {out}")
        except Exception as ex:
            print(f"AI FAILED: {ex}")
            sys.exit(1)
        st = N.status()
        print("Channels: text/call via Twilio = " + ("ON" if st["sms"] else "off") + ", email = " + ("ON" if st["email"] else "off"))
        sys.exit(0)
    # set up HTTP server
    PORT = a.port
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f"\n  Upline is running\n     Laptop:  http://localhost:{a.port}\n     Phone (same Wi-Fi):  "
          f"http://{lan_ip()}:{a.port}\n     AI phrasing layer: {'ON (' + C.model + ')' if C.llm_enabled else 'built-in (no API key needed)'}\n"
          f"     Real alerts: text/call {'ON' if N.status()['sms'] else 'off'} · email {'ON' if N.status()['email'] else 'off'} · app notifications ON\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
else:
    PORT = 8000
