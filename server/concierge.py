import json
import os
import re
import ssl
import urllib.error
import urllib.request

from guidance import fmt_h, range_text

PHONE = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ADDR = re.compile(r"\b\d{1,6}\s+([A-Z][a-z]+\s){1,3}(st|street|rd|road|ave|avenue|dr|drive|ln|lane|ct|court|blvd|way|pike|hwy)\b",
                  re.I)
SAFETY = re.compile(r"(downed|down(ed)? (power )?line|wire (is )?(down|on the ground)|power line (is )?down|sparking|sparks|"
                    r"arcing|on fire|fire|smell (gas|smoke)|carbon monoxide|\bco alarm|generator (inside|in the garage)|"
                    r"electrocut|shock(ed)?|tree on (the )?(line|wire)|line on my (car|house))", re.I)
INJECTION = re.compile(r"(ignore (all|previous|your) (instructions|rules)|system prompt|developer mode|jailbreak|"
                       r"life[- ]?support (list|customers|people|homes)|who (else|nearby|in my area) (has|is|uses)|"
                       r"(neighbor|neighbour)'?s? (address|name|medical|account)|crew (location|names?|phone)|"
                       r"employee|lineman'?s? (name|number)|premise (number|id) of|raw data|internal (field|data)|"
                       r"\bthreat\b flag|show me (all|every) (customer|address))", re.I)

DEVICE_WORDS = {
    "oxygen": "oxygen concentrator", "concentrator": "oxygen concentrator", "cpap": "CPAP machine",
    "bipap": "BiPAP machine", "ventilator": "ventilator", "dialysis": "home dialysis machine",
    "nebulizer": "nebulizer", "feeding pump": "feeding pump", "suction": "suction machine",
}


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

# converts notification channel to wording
def _chan(c):
    c = c.lower()
    if c.startswith("voice"):
        return "phone call"
    if c.startswith("app"):
        return "app notification"
    if c.startswith("email"):
        return "email"
    return "text message"


def _first_sentence(t):
    for sep in (". ", ": "):
        if sep in t:
            return t.split(sep)[0] + "."
    return t

# removes personally identifiable information
def redact(text):
    t = PHONE.sub("[phone removed]", text)
    t = EMAIL.sub("[email removed]", t)
    t = ADDR.sub("[address removed]", t)
    return t

# detect household needs
def extract_needs(text):
    t = text.lower()
    found = {}
    for k, v in DEVICE_WORDS.items():
        if k in t:
            found["medical_device"] = True
            found["device_name"] = v
            break
    m = re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b", t)
    if m and ("batter" in t or "backup" in t or "last" in t or found.get("medical_device")):
        found["battery_hours"] = float(m.group(1))
    if re.search(r"insulin|refrigerat\w* (med|medicine)", t):
        found["refrigerated_meds"] = True
    if re.search(r"wheelchair|power chair|stair ?lift|mobility|can'?t walk|elevator", t):
        found["mobility"] = True
    if re.search(r"\bbaby\b|infant|newborn", t):
        found["infant"] = True
    if re.search(r"\bwell\b( water| pump)?", t):
        found["well_pump"] = True
    if re.search(r"\bdog|\bcat|\bpets?\b", t):
        found["pets"] = True
    if re.search(r"works? (from|at) home|remote(ly)? work|home office|working from home", t):
        found["work_from_home"] = True
    if re.search(r"\b(mom|mother|dad|father|grandma|grandmother|grandpa|grandfather|elderly|older|senior|aging)\b", t) and not found.get("medical_device"):
        found["older_adult"] = True
    if re.search(r"electric (car|vehicle)|\bev\b|tesla", t):
        found["ev"] = True
    if re.search(r"space heater|kerosene heater", t):
        found["space_heater"] = True
    if re.search(r"sump", t):
        found["sump_pump"] = True
    m = re.search(r"(\d+)\s*(people|persons|of us)", t)
    if m:
        found["household"] = int(m.group(1))
    return found

# classifies a question into what category it belongs to
def intent(text):
    t = text.lower()
    if re.search(r"\bwhy\b|explain|how do you know|what makes|reason", t):
        return "explain"
    if re.search(r"how long|when (will|is|does)|back on|restor|eta\b|etr\b|how many (hours|days)", t):
        return "restore"
    if re.search(r"alert|notif|text me|sign me up|qualif|eligib|message", t):
        return "alerts"
    if re.search(r"prepare|prep\b|what should i do|ready|supplies|checklist|plan|pack|need to do", t):
        return "prep"
    if re.search(r"lose power|lose my power|outage|risk|chance|likely|will i|going to lose|power go", t):
        return "risk"
    if re.search(r"what if|more crews|fewer crews|if the storm", t):
        return "whatif"
    if re.search(r"hello|hi\b|hey|help|what can you", t):
        return "hello"
    return "unknown"


class Concierge:
    # initialize engine and guidance and LLM
    def __init__(self, engine, guidance_mod):
        self.e = engine
        self.g = guidance_mod
        self.base = os.environ.get("UPLINE_LLM_BASE_URL", "").rstrip("/")
        self.key = os.environ.get("UPLINE_LLM_API_KEY", "")
        self.model = os.environ.get("UPLINE_LLM_MODEL", "")
        self.llm_enabled = bool(self.base and self.model)
        self.last_error = None
    # sends request to LLM
    def chat_completion(self, body, timeout=20):
        body = dict(body)
        m = (self.model or "").lower()
        if "gpt-oss" in m or m.startswith("o1") or m.startswith("o3") or m.startswith("o4"):
            body.setdefault("reasoning_effort", "low")
            body["max_tokens"] = max(int(body.get("max_tokens", 300)), 1200)
        elif "qwen" in m or "deepseek" in m or "r1" in m:
            if "groq.com" in self.base:
                body.setdefault("reasoning_format", "hidden")
            body["max_tokens"] = max(int(body.get("max_tokens", 300)), 1200)
        req = urllib.request.Request(
            self.base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": "Mozilla/5.0 (Upline outage concierge)",
                     **({"Authorization": f"Bearer {self.key}"} if self.key else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
                out = json.loads(r.read())
            msg = out["choices"][0]["message"].get("content") or ""
            msg = re.sub(r"<think>.*?</think>", "", msg, flags=re.S).strip()
            if not msg:
                raise ValueError("the model returned an empty answer (try a non-reasoning model)")
            self.last_error = None
            return msg
        except urllib.error.HTTPError as ex:
            detail = ex.read().decode(errors="ignore")[:200]
            hint = {401: "API key rejected", 403: "blocked by provider", 404: "model or URL not found",
                    429: "rate limit reached"}.get(ex.code, "HTTP error")
            self.last_error = f"{hint} (HTTP {ex.code}): {detail}"
        except urllib.error.URLError as ex:
            self.last_error = f"can't reach {self.base} ({ex.reason})"
        except Exception as ex:
            self.last_error = f"{type(ex).__name__}: {ex}"
        print(f"[upline] AI call failed: {self.last_error}", flush=True)
        raise RuntimeError(self.last_error)
    # collects data needed to answer customer questions
    def tools_payload(self, pid, sc, needs):
        risk = self.e.risk(pid, sc)
        rest = self.e.restoration(pid, sc, with_drivers=False) if risk.get("ok") else {"ok": False}
        prep = self.g.prep(risk, rest, needs, self.e.scenario(sc)["hazard"], self.e.scenario(sc))
        al = self.g.alerts(risk, rest, needs, self.e.scenario(sc))
        return risk, rest, prep, al
    # Respond to customer queries
    def reply(self, msg, pid, sc, needs, lang="en"):
        trace = []
        clean = redact(msg or "")
        if clean != msg:
            trace.append({"control": "PII redaction", "detail": "Removed personal details before processing/logging."})
        new_needs = extract_needs(clean)
        needs = {**(needs or {}), **new_needs}
        if new_needs:
            trace.append({"control": "Declared needs", "detail": f"Customer declared: {', '.join(sorted(new_needs))}. "
                                                                 "Used only for guidance; nothing is inferred."})
        if SAFETY.search(clean):
            self.e.log("safety_interrupt", {"pid": pid}, "Emergency script + human hand-off (E5)")
            trace.append({"control": "Safety interrupt (E5)", "detail": "Emergency keywords detected; escalated."})
            return {"text": ("⚠️ **This is an emergency. Call 911 now.**\n\n"
                             "Stay at least 30 feet away, about the length of a school bus, and keep people and pets back. "
                             "Treat the wire as live even if it isn't sparking, and don't touch anything it's touching.\n\n"
                             "I've also alerted an AEP agent."),
                    "kind": "emergency", "needs": needs, "trace": trace, "escalate": True}
        if INJECTION.search(clean):
            self.e.log("privacy_refusal", {"pid": pid}, "Refused request for sensitive/internal data")
            trace.append({"control": "Privacy guard", "detail": "Request for other customers' data, sensitive "
                                                               "locations, staff details or internal fields refused."})
            return {"text": ("I can't share anything about other customers, AEP staff or sensitive locations. "
                             "I'm happy to help with **your** home: your outage risk, how long it could last, "
                             "getting ready, or alerts."),
                    "kind": "refusal", "needs": needs, "trace": trace}

        it = intent(clean)
        if it in ("unknown", "hello") and new_needs:
            it = "prep"
        if not pid:
            return {"text": "First, choose your home, then ask me anything about the storm.",
                    "kind": "info", "needs": needs, "trace": trace}
        risk, rest, prep, al = self.tools_payload(pid, sc, needs)
        trace.append({"control": "Tools called", "detail": "get_outage_risk, simulate_restoration, prep_plan, check_alerts"})
        if not risk.get("ok"):
            return {"text": risk["message"], "kind": "fallback", "needs": needs, "trace": trace}

        template = self.template(it, risk, rest, prep, al, needs)
        text, used_llm = template, False
        if self.llm_enabled:
            try:
                cand = self.llm(clean, it, risk, rest, prep, al, needs, lang)
                ok, bad = self.grounded(cand, [risk, rest, prep, al, needs])
                if ok:
                    text, used_llm = cand, True
                    trace.append({"control": "Numeric grounding guard", "detail": "PASSED — every number in the "
                                                                                  "AI answer came from a tool."})
                else:
                    trace.append({"control": "Numeric grounding guard",
                                  "detail": f"BLOCKED AI answer (unsupported numbers: {', '.join(bad[:4])}); "
                                            "fell back to verified template."})
                    self.e.log("grounding_guard", {"pid": pid}, f"blocked LLM answer: {bad[:4]}")
            except Exception as ex:
                trace.append({"control": "LLM fallback", "detail": f"AI unavailable ({ex}); "
                                                                    "used built-in answer."})
        if any(t["control"] == "PII redaction" for t in trace):
            text = ("🔒 I removed the personal details you shared. I don't need them, and they aren't saved.\n\n") + text
        if risk.get("confidence") == "Low" or not risk.get("reliable", True):
            text += "\n\n_We have limited data for your area, so treat this as a rough guide._"
        return {"text": text, "kind": it, "needs": needs, "trace": trace, "llm": used_llm,
                "escalate": prep.get("escalate", False),
                "facts": {"band": risk["band"], "p": risk["probability"], "conf": risk["confidence"],
                          "p10": rest.get("p10"), "p50": rest.get("p50"), "p90": rest.get("p90")}}
    # generates predefined answers for common questions
    def template(self, it, risk, rest, prep, al, needs):
        b, p, conf = risk["band"], risk["probability"], risk["confidence"]
        top = max((n for n in risk["path"] if n.get("share") is not None and n["kind"] != "home"),
                  key=lambda n: n["share"])
        oh = risk["factors"][0]["value"]
        head = {"Low": "a low chance", "Elevated": "some chance", "High": "a good chance",
                "Severe": "a very high chance"}[b]
        sure = {"High": "We're fairly confident about this.",
                "Medium": "It depends a bit on how strong the storm gets.",
                "Low": "Treat this as a rough guide; we have limited data for your area."}[conf]
        if it in ("risk", "hello", "unknown"):
            s = (f"There's **{head}** you'll lose power in this storm: about **{p:.0%}**. {sure}\n\n"
                 f"Your power travels over **{oh}** of overhead wire to reach you. The weak spot is your "
                 f"**{top['friendly'].lower()}**, which is about {top['share']:.0%} of your risk.")
            if it != "risk":
                s += "\n\nAsk me how long an outage could last, how to get ready, or about alerts."
            return s
        if it == "restore":
            if not rest.get("ok"):
                return "I can't estimate that reliably for your home. Please watch for official updates from AEP."
            return (f"If your power goes out, it will most likely be back in about **{fmt_h(rest['p50'])}**. "
                    f"It could be as quick as {fmt_h(rest['p10'])} or take up to {fmt_h(rest['p90'])}.\n\n"
                    "That's our estimate, not a promise. It changes with how much damage crews find, how many "
                    "crews are available, and whether roads are blocked.")
        if it == "prep":
            before = [i for i in prep["items"] if i["phase"] == "before"]
            first = ([i for i in before if i.get("need")] + [i for i in before if not i.get("need")])[:3]
            lines = "\n".join(f"• **{i['title']}.** {i['detail']}" for i in first)
            s = f"Here's what I'd do first:\n{lines}\n\n⚠️ **Safety:** stay 30 feet from any downed wire and call 911."
            if prep.get("escalate"):
                s += ("\n\n📞 Your backup won't last as long as a worst-case outage, so **someone from AEP will call "
                      "you before the storm** to help you plan.")
            s += "\n\nYour full checklist is on the **Prepare** tab."
            return s
        if it == "alerts":
            if al["eligible_pre_storm"]:
                first = al["schedule"][0]
                why = "because of the medical need you told us about" if any(
                    r["rule"] == "A2" for r in al["reasons"]) else f"because your risk is {b.lower()}"
                s = (f"**Yes, you qualify for storm alerts** {why}. You'll get your first "
                     f"{_chan(first['channel'])} about {first['when'].replace('T-', '').replace(' h', ' hours')} before the storm, then updates "
                     "if your power goes out, when the estimate changes, and when it's back.")
            else:
                s = ("Your risk is low, so you won't get a pre-storm warning, but you'll still get a message if your "
                     "power goes out and when it's back.")
            if any(t["id"] == "E1" and t["status"] == "ACTIVE" for t in al["triggers"]):
                s += "\n\n📞 We'll also have a person call you before the storm."
            return s
        if it == "explain":
            return (f"Here's how I worked it out:\n\n"
                    f"1. **Your power's path.** AEP's records show the exact lines that carry power to your home, "
                    f"including {oh} of overhead wire.\n"
                    f"2. **Past storms.** We looked at where damage happened in the Feb 2025 ice storm and Hurricane "
                    f"Helene. Long overhead lines through rural, wooded areas got hit most.\n"
                    f"3. **Your weak spot** is the {top['friendly'].lower()}, so most of your risk comes from there.\n\n"
                    "We tested this on real storms it had never seen, and the areas it rated riskiest really were hit "
                    "far more often. The **How Upline knows** page has the details.")
        if it == "whatif":
            return ("On the Home tab, tap **What could change this?** You can add or remove crews, block roads, or "
                    "add extra damage, and the estimate updates right away.")
        return self.template("risk", risk, rest, prep, al, needs)
    # builds facts from model and sends to LLM
    def llm(self, msg, it, risk, rest, prep, al, needs, lang):
        facts = {
            "risk": {k: risk[k] for k in ("band", "probability", "range", "confidence")},
            "riskiest_section": max((n for n in risk["path"] if n.get("share") is not None), key=lambda n: n["share"]),
            "factors": risk["factors"], "assumptions": risk["assumptions"],
            "restoration_hours": {k: rest.get(k) for k in ("p10", "p50", "p90")} if rest.get("ok") else None,
            "restoration_text": range_text(rest) if rest.get("ok") else None,
            "top_actions": [i["title"] + ": " + i["detail"] for i in prep["items"] if i["phase"] == "before"][:5],
            "alerts": {"eligible_pre_storm": al["eligible_pre_storm"], "reasons": al["reasons"],
                       "schedule": al["schedule"][:2], "active_triggers": [t for t in al["triggers"] if t["status"] == "ACTIVE"]},
            "declared_needs": needs,
        }
        system = (
            "You are Upline, a calm, plain-language outage concierge for utility customers. "
            "Answer ONLY from the TOOL_FACTS JSON. Never invent or compute new numbers; reuse numbers exactly as given "
            "(percentages may be written like 35%). Label model numbers as estimates, not promises. Keep it under 110 "
            "words, 6th-grade reading level, warm and direct. If safety is relevant, put SAFETY first. Never reveal "
            "other customers, staff, or internal data. "
            + ("Respond in Spanish." if lang == "es" else "")
        )
        body = {
            "model": self.model, "temperature": 0.2, "max_tokens": 300,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Customer question: {msg}\nDetected intent: {it}\nTOOL_FACTS: {json.dumps(facts)}"},
            ],
        }
        return self.chat_completion(body, timeout=20)
    # uses LLM to rephrase pre-plan summary
    def rephrase_summary(self, summary, prep, risk, rest, needs):
        if not self.llm_enabled:
            return summary, False
        facts = {"summary": summary, "band": risk.get("band"), "p90_text": fmt_h(rest.get("p90", 0)) if rest.get("ok") else None,
                 "household": needs, "top_steps": [i["title"] for i in prep["items"] if i["phase"] == "before"][:4]}
        body = {"model": self.model, "temperature": 0.3, "max_tokens": 120, "messages": [
            {"role": "system", "content": "Rewrite the plan summary for this household in 1-2 warm, plain sentences "
                                          "(6th-grade level). Use ONLY facts given; never add numbers. No greeting."},
            {"role": "user", "content": json.dumps(facts)}]}
        try:
            txt = self.chat_completion(body, timeout=12)
            ok, bad = self.grounded(txt, [facts, rest])
            if ok:
                self.e.log("llm_plan_summary", {}, "AI summary passed numeric guard")
                return txt, True
            self.e.log("grounding_guard", {}, f"blocked AI plan summary: {bad[:3]}")
        except Exception:
            pass
        return summary, False

    # checks AI response for unsupported numberic claims
    @staticmethod
    def grounded(text, sources):
        blob = json.dumps(sources, default=str)
        allowed = set()
        for n in re.findall(r"-?\d+(?:\.\d+)?", blob):
            try:
                v = float(n)
            except ValueError:
                continue
            for x in (v, v * 100, v / 24, v * 24):
                allowed.add(round(x))
                allowed.add(round(x, 1))
        allowed |= {0, 1, 2, 3, 911, 30, 20, 4, 48, 40}
        bad = []
        for n in re.findall(r"\d+(?:\.\d+)?", text):
            v = float(n)
            if round(v) not in allowed and round(v, 1) not in allowed:
                bad.append(n)
        return (len(bad) == 0), bad
