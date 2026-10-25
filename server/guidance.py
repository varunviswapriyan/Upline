def fmt_h(h, lang="en"):
    h = max(0.0, float(h))
    if lang == "en" and h >= 36:
        d = round(h / 24 * 2) / 2
        whole = int(d)
        return f"{whole}½ days" if d - whole else f"{whole} days"
    if lang == "es":
        if h < 1:
            return "menos de 1 hora"
        if h < 36:
            return f"{round(h)} horas"
        return f"{h / 24:.1f} días".replace(".0 días", " días")
    if h < 1:
        return "under 1 hour"
    if h < 36:
        return f"{round(h)} hours"
    d = h / 24
    return f"{d:.1f} days".replace(".0 days", " days")


def range_text(r, lang="en"):
    if lang == "es":
        return f"{fmt_h(r['p10'], 'es')} a {fmt_h(r['p90'], 'es')}"
    return f"{fmt_h(r['p10'])} to {fmt_h(r['p90'])}"


NEED_TAGS = {
    "medical_device": "🫁 {device}", "refrigerated_meds": "💊 Fridge medicine", "mobility": "♿ Mobility needs",
    "infant": "👶 Baby", "pets": "🐾 Pets", "well_pump": "💧 Well water", "critical_facility": "🏫 Facility",
    "older_adult": "🧓 Older adult at home", "work_from_home": "💻 Works from home", "ev": "🔌 Electric car",
    "space_heater": "🔥 Space heater", "sump_pump": "🌊 Sump pump", "household": "👪 {n} people",
}


def need_labels(needs):
    out = []
    for k, t in NEED_TAGS.items():
        v = needs.get(k)
        if k == "household":
            out.append(t.format(n=int(needs.get("household", 2) or 2)))
        elif v:
            out.append(t.format(device=(needs.get("device_name") or "Medical equipment").capitalize()))
    return out


def prep(risk, rest, needs, hazard, sc=None):
    needs = needs or {}
    sc = sc or {}
    items = []
    band = risk.get("band", "Elevated") if risk.get("ok") else "Elevated"
    p90 = rest.get("p90", 48) if rest and rest.get("ok") else 48
    p50 = rest.get("p50", 24) if rest and rest.get("ok") else 24
    days = max(1, min(7, round(p90 / 24 + 0.49)))
    people = int(needs.get("household", 2) or 2)
    escalate = False
    storm_tag = {"ice": "❄️ Ice storm", "tropical": "🌀 Tropical storm", "wind": "⛈️ Thunderstorms"}.get(hazard, "🌩️ This storm")
    dev = (needs.get("device_name") or "medical device")

    def add(phase, cat, title, detail, why, priority=2, src="general", tag=None):
        items.append({"phase": phase, "category": cat, "title": title, "detail": detail, "why": why,
                      "priority": priority, "need": src == "you", "source": src, "tag": tag,
                      "text": f"{title}. {detail}".replace("..", ".")})

    add("safety", "SAFETY", "Stay 30 feet from downed wires",
        "That's about a school bus length. Treat every wire as live and call 911.",
        "Downed lines can energize the ground around them.", 0)
    add("safety", "SAFETY", "Never run a generator indoors",
        "Keep it at least 20 feet from doors and windows. Use a battery carbon-monoxide alarm.",
        "Carbon monoxide is a leading cause of storm deaths.", 0)
    if hazard == "ice":
        add("safety", "SAFETY", "Stay out from under icy trees and lines",
            "Ice-loaded limbs and wires can fall without warning.", "Ice can add hundreds of pounds to a branch.", 0)
    if hazard == "tropical":
        add("safety", "SAFETY", "Don't drive through flood water",
            "It can hide downed lines and washed-out roads.", "Heavy rain is expected with this storm.", 0)

    if needs.get("medical_device"):
        t = NEED_TAGS["medical_device"].format(device=dev.capitalize())
        batt = needs.get("battery_hours")
        if batt is not None and float(batt) < p90:
            escalate = True
            add("before", "EMERGENCY PLAN", f"Get more backup power for the {dev}",
                f"Its battery lasts about {fmt_h(batt)}, but your power could be out up to {fmt_h(p90)}.",
                "Your backup is shorter than our worst-case estimate.", 0, "you", t)
            add("before", "EMERGENCY PLAN", "Pick a place with power to go to",
                "A relative, friend or shelter. Decide now, not during the outage.",
                "Restoration times are estimates, not promises.", 0, "you", t)
        elif batt is not None:
            add("before", "PREPARE NOW", f"Fully charge the {dev} backup",
                f"It lasts about {fmt_h(batt)}, which covers our worst case of {fmt_h(p90)}.",
                "Your backup covers the estimate, if it's fully charged.", 1, "you", t)
        else:
            add("before", "EMERGENCY PLAN", f"Check how long the {dev} backup lasts",
                "Tell us the hours so we can compare it with your outage estimate.", "Needed to plan your backup.", 0, "you", t)
        add("before", "PREPARE NOW", "Ask AEP about medical priority alerts",
            "And tell your care provider about your outage plan.", "Medical customers can get earlier warnings.", 1, "you", t)
        add("during", "EMERGENCY PLAN", "If the backup runs low, go to your safe place",
            "Call 911 if it's life-threatening. Don't wait for the power to return.", "Your declared medical need.", 0, "you", t)
    if needs.get("refrigerated_meds"):
        t = NEED_TAGS["refrigerated_meds"]
        add("before", "PREPARE NOW", "Get a cooler and ice packs for medicine",
            "Ask your pharmacist how long it stays good without a fridge.", f"Power could be out up to {fmt_h(p90)}.", 1, "you", t)
        add("during", "DURING", "Move medicine to the cooler after 4 hours",
            "Keep the fridge shut until then.", "Fridges stay cold about 4 hours.", 1, "you", t)
    if needs.get("mobility"):
        t = NEED_TAGS["mobility"]
        add("before", "PREPARE NOW", "Charge your power chair or lift",
            "And arrange for someone to check on you each day.", "Lifts and elevators stop in an outage.", 1, "you", t)
    if needs.get("older_adult"):
        t = NEED_TAGS["older_adult"]
        add("before", "PREPARE NOW", "Set up a daily check-in", "A call or visit each day the power is out.",
            "Older adults are more at risk from cold and heat.", 1, "you", t)
    if needs.get("infant"):
        t = NEED_TAGS["infant"]
        add("before", "PREPARE NOW", "Stock ready-to-feed formula and water",
            "No mixing or heating needed.", "You may not have a stove or hot water.", 1, "you", t)
        add("during", "DURING", "Keep the baby warm in layers", "Use a hat and a warm room you can close off.",
            "Babies lose heat faster than adults.", 1, "you", t)
    if needs.get("well_pump"):
        t = NEED_TAGS["well_pump"]
        add("before", "PREPARE NOW", "Fill tubs and jugs with water", "For washing and flushing toilets.",
            "Your well pump can't run without power.", 1, "you", t)
    if needs.get("sump_pump"):
        t = NEED_TAGS["sump_pump"]
        add("before", "PREPARE NOW", "Check your sump pump's battery backup", "Move things off the basement floor.",
            "Your sump pump stops in an outage.", 1, "you", t)
    if needs.get("work_from_home"):
        t = NEED_TAGS["work_from_home"]
        add("before", "PREPARE", "Charge your laptop and set up a phone hotspot",
            "Download anything you'll need offline.", "Your internet router needs power.", 2, "you", t)
    if needs.get("ev"):
        t = NEED_TAGS["ev"]
        add("before", "PREPARE", "Charge your car to full tonight", "Your charger won't work during the outage.",
            f"Power could be out up to {fmt_h(p90)}.", 2, "you", t)
    if needs.get("space_heater"):
        t = NEED_TAGS["space_heater"]
        add("after", "AFTER", "Keep space heaters 3 feet from anything that burns",
            "Don't leave them on overnight or unattended.", "Space heaters are a top cause of winter fires.", 1, "you", t)
    if needs.get("pets"):
        t = NEED_TAGS["pets"]
        add("before", "PREPARE", f"Pack {days} days of pet food and water", "Plus any medicine they take.",
            "Sized to your worst-case estimate.", 2, "you", t)
    if needs.get("critical_facility"):
        t = NEED_TAGS["critical_facility"]
        add("before", "FACILITY", "Test your backup generator and fuel",
            f"Plan for at least {fmt_h(p90)} without grid power.", "You told us this is a critical facility.", 0, "you", t)
        add("before", "FACILITY", "Confirm your 24/7 contact with AEP",
            "So crews can reach the right person fast.", "Critical-facility escalation.", 1, "you", t)
    hh = NEED_TAGS["household"].format(n=people)
    if band in ("High", "Severe"):
        add("before", "PREPARE NOW", f"Store {days * people} gallons of water",
            f"1 gallon per person per day, for {people} people and {days} day{'s' if days > 1 else ''}.",
            "Sized to your household and your worst-case estimate.", 1, "you", hh)

    home_tag = "🏠 Your power line"
    path = risk.get("path") or []
    zones = [n for n in path if n.get("kind") in ("fuse", "recloser", "sectionalizer", "breaker")]
    if zones:
        first = zones[0]
        oh = sum(float(str(f.get("value", "0")).split()[0]) for f in risk.get("factors", [])[:1]) if risk.get("factors") else 0
        if first.get("down", 9999) < 150 and p90 > 30:
            add("before", "PREPARE NOW", "Plan for the long end of the estimate",
                f"Your street's line serves only about {first['down']} homes. Crews fix lines serving the most homes "
                "first, so yours may come later.",
                f"Repair order in our crew simulation; worst case {fmt_h(p90)}.", 1, "home", home_tag)
        elif band in ("High", "Severe"):
            add("before", "PREPARE NOW", f"Plan for up to {fmt_h(p90)} without power",
                "That's our worst-case estimate for your home.", f"Your outage chance is {risk.get('probability', 0):.0%}.",
                1, "home", home_tag)
        if oh >= 3:
            add("during", "DURING", "No damage on your street? It may be miles away",
                f"Your power travels {oh:.1f} miles on overhead wire, so the break can be far up the line.",
                "From your home's power path in AEP's records.", 2, "home", home_tag)
    svc = (path[0].get("detail", "") if path else "")
    if svc.startswith("Overhead"):
        add("after", "AFTER", "Check the wire from the pole to your house",
            "If it's sagging or down, keep away and report it. It's a repair just for your home.",
            "You have an overhead service wire.", 1, "home", home_tag)
    elif svc.startswith("Underground"):
        add("before", "PREPARE", "Your wires are buried, so risk comes from up the line",
            "Storms rarely damage underground service, but the lines feeding your street can fail.",
            "You have underground service.", 3, "home", home_tag)

    hts = int(sc.get("hours_to_storm", 24) or 24)
    if band in ("High", "Severe"):
        add("before", "PREPARE NOW", "Charge phones and power banks " + ("now" if hts <= 12 else "tonight"),
            "Your phone is how you'll get updates and call for help.", f"The storm arrives in about {hts} hours.",
            1, "storm", storm_tag)
    if hazard == "ice":
        if p90 >= 24:
            add("before", "PREPARE", "Let faucets drip so pipes don't freeze", "Open cabinet doors under sinks too.",
                f"A cold outage could last {fmt_h(p90)}.", 2, "storm", storm_tag)
        add("before", "PREPARE", "Gather blankets and warm layers", "Pick one room to keep warm and close the others.",
            "Ice storms bring cold with the outage.", 2, "storm", storm_tag)
    elif hazard == "tropical":
        add("before", "PREPARE", "Clear gutters and storm drains", "And move your car away from big trees.",
            "Heavy rain and wind are expected.", 2, "storm", storm_tag)
    elif hazard == "wind":
        add("before", "PREPARE", "Bring in or tie down outdoor furniture", "Wind can throw it into windows or lines.",
            "Strong gusts are expected.", 2, "storm", storm_tag)

    add("before", "PREPARE", "Freeze water bottles", "They keep your fridge and freezer cold longer.",
        f"A typical outage could last {fmt_h(p50)}.", 2)
    add("before", "PREPARE", "Find your flashlights and batteries", "Keep them where you can reach them in the dark.",
        "Basic storm kit.", 3)
    if p90 > 24:
        add("before", "PREPARE", "Pick a warm place to go", "A friend, family or a public warming center.",
            f"Worst case is {fmt_h(p90)}.", 2)
    add("during", "DURING", "Keep the fridge and freezer closed",
        "Food stays safe about 4 hours in the fridge and 48 hours in a full freezer.",
        f"A typical outage here could last {fmt_h(p50)}.", 1)
    add("during", "DURING", "Use flashlights, not candles", "Candles are a common cause of fires during outages.", "Fire safety.", 1)
    add("during", "DURING", "Unplug TVs and computers", "Protects them from a surge when power returns.",
        "Power can flicker as crews restore lines.", 2)
    add("during", "DURING", "Report damage you can see", "Use Upline from a safe distance. It helps crews plan.",
        "Your reports update the repair plan.", 2)
    add("during", "DURING", "Check on neighbors who live alone", "Especially older neighbors or anyone on medical equipment.",
        "Community safety.", 3)
    add("after", "AFTER", "Wait a few minutes before using big appliances", "This avoids overloading the line as it comes back.",
        "Helps prevent a second outage.", 1)
    add("after", "AFTER", "Throw out food that got warm", "Anything above 40°F for 2 hours or more.", "Avoids food poisoning.", 1)
    add("after", "AFTER", "Still out when neighbors are back? Tell us", "The problem may be the wire to your house only.",
        "Single-home outages can be missed.", 2)
    add("after", "AFTER", "Restock your kit", "Water, batteries and medicine for next time.", "Be ready for the next storm.", 3)

    order = {"you": 0, "home": 1, "storm": 2, "general": 3}
    items.sort(key=lambda x: (x["priority"], order[x["source"]]))
    summary = plan_summary(items, needs, band, p50, p90, hazard)
    return {"items": items, "escalate": escalate, "plan_days": days, "summary": summary,
            "profile": need_labels(needs)}


def plan_summary(items, needs, band, p50, p90, hazard):
    you = [i for i in items if i["source"] == "you" and i["phase"] == "before"]
    lead = {"Low": "Your outage risk is low", "Elevated": "An outage is possible",
            "High": "An outage is likely", "Severe": "An outage is very likely"}[band]
    s = f"{lead}, and it could last up to {fmt_h(p90)}. "
    if any(i["category"] == "EMERGENCY PLAN" for i in you):
        s += f"Your top priority is backup power for the {needs.get('device_name') or 'medical device'}, "
        s += "because its battery won't last that long."
    elif you:
        s += f"Start with: {you[0]['title'].lower()}."
    else:
        s += "Tell us about your household and we'll tailor these steps."
    return s


RULES = [
    {"id": "A1", "rule": "Pre-storm alert if risk band is Elevated or higher", "applies": "everyone with a contact on file"},
    {"id": "A2", "rule": "Pre-storm alert at ANY risk if the customer declared a medical, mobility or critical-facility need",
     "applies": "declared needs"},
    {"id": "A3", "rule": "Outage-confirmed, estimate-updated and restored messages for every enrolled customer",
     "applies": "all enrolled"},
    {"id": "E1", "rule": "Escalate to a phone call + human agent when declared backup hours < P90 restoration",
     "applies": "declared medical device"},
    {"id": "E2", "rule": "Send 'estimate updated' when the P50 moves by more than 2 hours or 25%", "applies": "all"},
    {"id": "E3", "rule": "Critical facility out > 4 h → utility account-manager escalation", "applies": "facilities"},
    {"id": "E4", "rule": "Forecast upgrade by one or more risk bands → resend pre-storm alert", "applies": "all"},
    {"id": "E5", "rule": "Safety keywords in chat (downed line, sparks, fire, CO) → emergency script + human hand-off",
     "applies": "all"},
    {"id": "E6", "rule": "Low model confidence → no numeric estimate is sent; message says 'assessing'",
     "applies": "all"},
]


def alerts(risk, rest, needs, sc, prefs=None):
    needs = needs or {}
    prefs = prefs or {}
    band = risk.get("band") if risk.get("ok") else None
    declared = bool(needs.get("medical_device") or needs.get("mobility") or needs.get("critical_facility")
                    or needs.get("refrigerated_meds"))
    reasons = []
    eligible_pre = False
    if band in ("Elevated", "High", "Severe"):
        eligible_pre = True
        reasons.append(("A1", f"Your outage risk is {band}."))
    if declared:
        eligible_pre = True
        reasons.append(("A2", "You declared a need that qualifies for early alerts."))
    if not eligible_pre:
        reasons.append(("—", f"Your risk is {band or 'unknown'}, so no pre-storm alert is required; you'll still get "
                              "outage and restoration updates."))
    reasons.append(("A3", "Outage, estimate-update and restoration messages apply to every enrolled customer."))

    batt = needs.get("battery_hours")
    p90 = rest.get("p90") if rest and rest.get("ok") else None
    triggers = []
    if needs.get("medical_device") and batt is not None and p90 is not None and float(batt) < p90:
        triggers.append({"id": "E1", "status": "ACTIVE", "text": f"Backup {fmt_h(float(batt))} < P90 {fmt_h(p90)} → "
                                                                  "phone call + human agent before the storm"})
    triggers.append({"id": "E2", "status": "armed", "text": "Re-send if the estimate moves by more than 2 h or 25%"})
    if needs.get("critical_facility"):
        triggers.append({"id": "E3", "status": "armed", "text": "Facility out > 4 h → account-manager escalation"})
    triggers.append({"id": "E4", "status": "armed", "text": "Forecast upgrade by a band → resend pre-storm alert"})
    triggers.append({"id": "E5", "status": "armed", "text": "Safety keywords → emergency script + human hand-off"})
    if risk.get("confidence") == "Low" or (rest and rest.get("confidence") == "Low"):
        triggers.append({"id": "E6", "status": "ACTIVE", "text": "Low confidence → messages omit numeric times"})

    hts = sc.get("hours_to_storm", 24)
    sched = []
    if eligible_pre:
        lead = 48 if declared else (24 if band in ("High", "Severe") else 12)
        sched.append({"when": f"T-{lead} h", "what": "Pre-storm alert", "channel": _channel(prefs, declared, urgent=False)})
        if band in ("High", "Severe") or declared:
            sched.append({"when": "T-6 h", "what": "Final reminder: charge devices, check backup plan",
                          "channel": _channel(prefs, declared, urgent=False)})
    sched += [
        {"when": "≤15 min after detection", "what": "Outage confirmed", "channel": _channel(prefs, declared, urgent=True)},
        {"when": "On change > 2 h", "what": "Estimate updated", "channel": _channel(prefs, declared, urgent=False)},
        {"when": "On restoration", "what": "Restoration complete + 'still out?' check after 30 min",
         "channel": _channel(prefs, declared, urgent=False)},
    ]
    return {"eligible_pre_storm": eligible_pre, "reasons": [{"rule": a, "text": b} for a, b in reasons],
            "triggers": triggers, "schedule": sched, "rules": RULES,
            "quiet_hours": "10 pm–7 am suppressed except safety, medical and critical-facility messages",
            "hours_to_storm": hts}


def _channel(prefs, declared, urgent):
    pref = prefs.get("channel", "sms")
    if declared and urgent:
        return "Voice call + SMS"
    return {"sms": "SMS", "push": "App push (SMS fallback)", "email": "Email + SMS", "voice": "Voice call"}.get(pref, "SMS")


def messages(risk, rest, needs, sc, lang="en", updated=None, live=None):
    low_conf = risk.get("confidence") == "Low" or (rest and rest.get("confidence") == "Low")
    band = risk.get("band", "Elevated")
    pct = f"{risk.get('probability', 0):.0%}"
    rng = range_text(rest, lang) if rest and rest.get("ok") else None
    rng2 = range_text(updated, lang) if updated and updated.get("ok") else rng
    med = needs.get("medical_device") if needs else None
    storm = {"ice": "ice storm", "tropical": "heavy wind and rain", "wind": "severe storms"}.get(sc.get("hazard"), "storm")
    hts = int(sc.get("hours_to_storm", 24))
    reason = (live or {}).get("reason")
    if lang == "es":
        storm_es = {"ice": "tormenta de hielo", "tropical": "viento y lluvia fuertes", "wind": "tormentas fuertes"}.get(
            sc.get("hazard"), "tormenta")
        band_es = {"Low": "baja", "Elevated": "moderada", "High": "alta", "Severe": "muy alta"}[band]
        m = {
            "pre_storm": f"Upline: Se espera {storm_es} en ~{hts} h. Probabilidad de apagón en su casa: {band_es} ({pct}). "
                         + (f"Si ocurre, la luz podría tardar {rng} (estimado). " if rng and not low_conf else "")
                         + ("Revise su plan de respaldo médico hoy. " if med else "")
                         + "Cargue sus teléfonos. Aléjese de cables caídos.",
            "outage_confirmed": "Upline: Confirmamos un apagón que afecta su casa. "
                                + (f"Causa probable: {reason}. " if reason else "")
                                + (f"Estimado inicial: {rng}. " if rng and not low_conf else "Estamos evaluando daños. ")
                                + "Aléjese de cables caídos y llame al 911 si ve uno.",
            "estimate_updated": "Upline: Estimado actualizado. "
                                + (f"Nuevo rango: {rng2}. " if rng2 and not low_conf else "")
                                + "Motivo: nuevas condiciones de daño o cuadrillas. Le avisaremos si cambia otra vez.",
            "restored": "Upline: ¡La luz volvió! Si sigue sin servicio, responda OUT. "
                        "Espere unos minutos antes de encender aparatos grandes.",
        }
    else:
        m = {
            "pre_storm": f"Upline: {storm.capitalize()} expected in about {hts} hours. Chance your home loses power: "
                         f"{ {'Low': 'low', 'Elevated': 'possible', 'High': 'likely', 'Severe': 'very likely'}[band]} ({pct}). "
                         + (f"If it goes out, power could be back in {rng} (estimate). " if rng and not low_conf else "")
                         + ("Check your medical backup plan today. " if med else "")
                         + "Charge phones now. Stay away from downed lines.",
            "outage_confirmed": "Upline: We've confirmed an outage affecting your home. "
                                + (f"Likely cause: {reason}. " if reason else "")
                                + (f"Our first estimate: power back in {rng}. " if rng and not low_conf else "Crews are checking the damage. ")
                                + "Stay clear of downed lines; call 911 if you see one.",
            "estimate_updated": "Upline: Estimate updated. "
                                + (f"New range: {rng2}. " if rng2 and not low_conf else "")
                                + ((updated or {}).get("why_text", "Reason: damage and crew conditions changed. ")
                                   if updated else "Reason: damage and crew conditions changed. ")
                                + "We'll text again if it changes.",
            "restored": "Upline: Power is restored at your home. Still out? Reply OUT. "
                        "Wait a few minutes before turning on large appliances.",
        }
    out = []
    labels = {"pre_storm": "Pre-storm", "outage_confirmed": "Outage confirmed",
              "estimate_updated": "Estimate updated", "restored": "Restoration complete"}
    for k, v in m.items():
        out.append({"type": k, "label": labels[k], "text": v.strip(), "chars": len(v.strip()),
                    "segments": (len(v.strip()) - 1) // 153 + 1})
    return out
