"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const BAND = {
  Low: { color: "#2E8B6E", word: "Unlikely" },
  Elevated: { color: "#C99A1F", word: "Possible" },
  High: { color: "#E0742C", word: "Likely" },
  Severe: { color: "#BF3A2B", word: "Very likely" },
};
const SURE = { High: "We're confident in this", Medium: "Depends on storm strength", Low: "Rough guess: limited data" };
const STORMS = {
  tstorm: { ico: "⛈️", title: "Thunderstorms expected", like: "A strong summer storm" },
  helene: { ico: "🌀", title: "Tropical storm expected", like: "Like Hurricane Helene, Sep 2024" },
  ice25: { ico: "❄️", title: "Ice storm expected", like: "Like the Feb 2025 ice storm" },
  extreme: { ico: "🌪️", title: "Extreme storm expected", like: "About twice as bad as Feb 2025" },
  custom: { ico: "🌩️", title: "Storm expected", like: "Custom strength" },
  live: { ico: "📡", title: "Live forecast", like: "From today's weather forecast" },
};
const HOME_ICO = ["🌲", "🏡", "🏙️"];

const S = {
  meta: null, pid: null, persona: null, data: null, base: null, lang: "en",
  preset: "ice25", liveNote: "",
  sc: { hazard: "ice", severity: 1, crew_pct: 100, mutual_aid_pct: 0, mutual_aid_hours: 24, extra_damage: 1, hours_to_storm: 24 },
  access: "usual", needs: { household: 2 }, prefs: { channel: "sms" },
  done: new Set(), reports: [], playing: false, speak: false, phase: "before", open: new Set(),
  contact: { phone: "", email: "" },
};

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = x => `${Math.round(x * 100)}%`;
const wait = ms => new Promise(r => setTimeout(r, ms));
function dur(h) {
  h = Math.max(0, +h);
  if (h < 1) return "under an hour";
  if (h < 36) return `${Math.round(h)} hours`;
  const d = Math.round(h / 24 * 2) / 2, w = Math.floor(d);
  return d - w ? `${w}½ days` : `${w} days`;
}
function md(s) {
  return esc(s).split(/\n{2,}/).map(p => "<p>" + p.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/_(.+?)_/g, "<i>$1</i>").replace(/\n/g, "<br>") + "</p>").join("");
}
function firstSentence(t) { const m = t.match(/^(.+?[.!?])(\s|$)/); return m ? m[1] : t; }
function rest(t) { const f = firstSentence(t); return t.slice(f.length).trim(); }
function scenario() {
  const def = Math.round(S.meta.model.access_rate * ({ ice: 1.15, tropical: 1.25, wind: 1 }[S.sc.hazard] || 1) * 100);
  const access_pct = { clear: Math.max(0, def - 25), usual: def, many: Math.min(100, def + 35) }[S.access];
  return { ...S.sc, access_pct, source: S.preset === "live" ? "live" : "preset" };
}
function zones(path) { return path.filter(n => ["fuse", "recloser", "sectionalizer", "breaker"].includes(n.kind)); }
function weakSpot(path) { return zones(path).slice().sort((a, b) => b.share - a.share)[0]; }

async function init() {
  S.meta = await api("/api/meta");
  $("#homes").innerHTML = homeOptions();
  bind();
  pitchQR();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  const q = new URLSearchParams(location.search);
  $("#splashGo").onclick = () => {
    $("#splash").classList.add("leave");
    setTimeout(() => { $("#splash").hidden = true; $("#welcome").hidden = false; $("#welcome").classList.add("enter"); }, 420);
  };
  if (q.get("pid")) { $("#splash").hidden = true; selectPid(q.get("pid")); }
  else if (q.get("judge")) { $("#splash").hidden = true; const r = await api("/api/random"); selectPid(r.pid); }
}

function homeOptions() {
  return S.meta.personas.map((p, i) => `<button class="home-opt" data-pid="${p.pid}">
      <span class="ico">${HOME_ICO[i] || "🏠"}</span>
      <span><b>${esc(p.label)}</b><small>${esc(p.city)} · ${p.svc === "U" ? "underground wires" : "overhead wires"}</small></span>
      <span class="go">›</span></button>`).join("");
}

function bind() {
  document.addEventListener("click", e => {
    const h = e.target.closest(".home-opt"); if (h) { closeSheet(); selectPid(h.dataset.pid); }
    const g = e.target.closest("[data-go]"); if (g) go(g.dataset.go);
  });
  $("#idForm").onsubmit = e => { e.preventDefault(); const v = $("#idInput").value.trim(); if (v) selectPid(v); };
  $("#mapPick").onclick = openMap;
  $("#homeChip").onclick = openHomePicker;
  $("#menuBtn").onclick = openSettings;
  $("#stormBanner").onclick = openStorm;
  $("#pathBtn").onclick = openPath;
  $("#whatIfBtn").onclick = openWhatIf;
  $("#reportBtn").onclick = openReport;
  $("#playBtn").onclick = playStorm;
  $("#trustBtn").onclick = openTrust;
  $("#safetyBtn").onclick = openSafety;
  $("#rulesBtn").onclick = openRules;
  $("#sheetClose").onclick = closeSheet;
  $("#scrim").onclick = closeSheet;
  $("#personalizeBtn").onclick = openHousehold;
  $("#chanSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; S.prefs.channel = b.dataset.c; segOn("#chanSeg", b); renderLive(); refreshRest(); };
  $("#langSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; S.lang = b.dataset.l; segOn("#langSeg", b); refreshRest(); };
  $("#askForm").onsubmit = e => { e.preventDefault(); const v = $("#askInput").value.trim(); if (v) { $("#askInput").value = ""; ask(v); } };
  $("#suggest").onclick = e => { const b = e.target.closest(".chip"); if (b) ask(b.textContent); };
  $("#micBtn").onclick = listen;
  document.addEventListener("click", e => {
    const c = e.target.closest(".check");
    if (c) { const k = c.dataset.k; S.done.has(k) ? S.done.delete(k) : S.done.add(k); renderPrep(); renderTopSteps(); return; }
    const m = e.target.closest(".p-main");
    if (m) { const k = m.dataset.k; S.open.has(k) ? S.open.delete(k) : S.open.add(k); m.closest("li").classList.toggle("open"); }
  });
  $("#phaseSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; segOn("#phaseSeg", b); S.phase = b.dataset.ph; renderPrep(); };
}
function segOn(sel, b) { $$(sel + " button").forEach(x => x.classList.toggle("on", x === b)); }

function go(tab) {
  $$(".screen").forEach(s => s.hidden = s.dataset.screen !== tab);
  $$(".tabbar button").forEach(b => b.classList.toggle("on", b.dataset.go === tab));
  $(".screens").scrollTop = 0;
  if (tab === "ask" && !$("#chatLog").children.length) botSay("Hi! I'm Upline. Ask me anything about your power and this storm. Tap the mic to talk.");
}

async function selectPid(pid) {
  pid = pid.toUpperCase().trim(); if (!pid.startsWith("UPL-")) pid = "UPL-" + pid;
  S.pid = pid; S.persona = S.meta.personas.find(p => p.pid === pid) || null; S.reports = []; S.done.clear();
  history.replaceState(null, "", `?pid=${pid}`);
  await load();
}

async function load() {
  let d;
  const body = { pid: S.pid, scenario: scenario(), needs: S.needs, lang: S.lang, prefs: S.prefs };
  try { d = await api("/api/assess", body); }
  catch (e) {
    await wait(1200);
    try { d = await api("/api/assess", body); }
    catch (e2) { return offline(); }
  }
  hideOffline();
  $("#splash").hidden = true;
  if (!d.risk.ok) {
    $("#welcome").hidden = false; $("#app").hidden = true;
    $(".welcome-top h1").textContent = "We couldn't find that home";
    $(".welcome-top p").textContent = "We can't make a reliable prediction for it. Pick another home, and get ready as if an outage is possible.";
    return;
  }
  S.data = d; S.base = d.restoration; S.notice = ""; S.newSet = null;
  $("#welcome").hidden = true; $("#app").hidden = false;
  $("#homeChipText").textContent = S.persona ? `${S.persona.city} home` : `${d.risk.city} home`;
  renderAll();
}

async function refreshRest(opts = {}) {
  if (!S.pid) return;
  const before = new Map((S.data?.prep?.items || []).map(i => [i.title, i]));
  const d = await api("/api/restoration", { pid: S.pid, scenario: scenario(), needs: S.needs, lang: S.lang, prefs: S.prefs, reports: S.reports });
  Object.assign(S.data, { restoration: d.restoration, prep: d.prep, alerts: d.alerts, messages: d.messages });
  if (opts.highlight) {
    const added = d.prep.items.filter(i => !before.has(i.title) && i.phase !== "safety");
    const removed = [...before.values()].filter(i => !d.prep.items.some(x => x.title === i.title) && i.phase !== "safety");
    S.newSet = new Set(added.map(i => i.title));
    const tags = [...new Set(added.map(i => i.tag).filter(Boolean))];
    const phases = [...new Set(added.map(i => i.phase))];
    S.notice = added.length || removed.length
      ? `<div class="notice"><span>✨</span><span><b>Your plan changed: ${added.length} new step${added.length === 1 ? "" : "s"}${removed.length ? `, ${removed.length} removed` : ""}</b>
         ${tags.length ? `Because of ${tags.join(", ")}.` : "Updated for your household."} ${phases.length > 1 || (phases[0] && phases[0] !== S.phase) ? `New steps are in ${phases.map(p => ({ before: "Before", during: "During", after: "After" }[p])).join(", ")}.` : "They're highlighted below."}</span></div>`
      : `<div class="notice"><span>✓</span><span><b>Saved.</b> Your plan already covers this.</span></div>`;
  }
  renderRestore(); renderTopSteps(); renderAlertMini(); renderPrep(); renderAlerts();
  return d;
}
function syncNeeds() {}

function renderAll() { renderStorm(); renderRisk(); renderRestore(); renderTopSteps(); renderAlertMini(); renderPrep(); renderAlerts(); renderLive(); syncNeeds(); }

function renderStorm() {
  const s = STORMS[S.preset] || STORMS.custom;
  $("#stormIco").textContent = s.ico;
  $("#stormTitle").textContent = s.title;
  $("#stormSub").textContent = `In about ${S.sc.hours_to_storm} hours · ${S.preset === "live" ? S.liveNote || s.like : s.like}`;
}

function renderRisk() {
  const r = S.data.risk, card = $("#riskCard");
  card.classList.remove("out", "back");
  const b = BAND[r.band];
  $("#riskTop").style.background = b.color;
  $("#riskK").textContent = "Chance you'll lose power"; $("#riskTag").textContent = "Estimate";
  $("#riskPct").textContent = pct(r.probability);
  $("#riskWord").textContent = b.word;
  $("#dial").innerHTML = dialSVG(r.probability);
  $("#sure").textContent = SURE[r.confidence];
  const w = weakSpot(r.path), ohMi = parseFloat(r.factors[0].value);
  $("#riskWhy").innerHTML = ohMi < 0.6
    ? `Your power comes mostly through <b>underground or short lines</b>, which storms rarely damage.`
    : `Your power travels <b>${esc(r.factors[0].value)} on overhead wires</b> to reach you. The weak spot is your <b>${esc(w.friendly.toLowerCase())}</b>.`;
  $("#strip").innerHTML = stripHTML(r.path);
  if (r.fallback_message) $("#riskWhy").innerHTML += `<br><small class="muted">${esc(r.fallback_message)}</small>`;
}

function dialSVG(p) {
  const segs = [[0, .1, "#2E8B6E"], [.1, .3, "#E8B83A"], [.3, .6, "#EE8A3E"], [.6, 1, "#7A1712"]];
  const R = 30, cx = 37, cy = 40;
  const pt = (t, r = R) => { const a = Math.PI * (1 - t); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
  let g = `<path d="M${pt(0)[0]} ${cy}A${R} ${R} 0 0 1 ${pt(1)[0]} ${cy}" stroke="rgba(255,255,255,.95)" stroke-width="13" fill="none"/>`;
  g += segs.map(([a, b, c]) => { const [x1, y1] = pt(a), [x2, y2] = pt(b); return `<path d="M${x1} ${y1}A${R} ${R} 0 0 1 ${x2} ${y2}" stroke="${c}" stroke-width="8" fill="none"/>`; }).join("");
  const [nx, ny] = pt(p, R - 4);
  g += `<line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="#fff" stroke-width="3.5" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="5" fill="#fff"/>`;
  return `<svg viewBox="0 0 74 50" role="img" aria-label="Risk gauge">${g}</svg>`;
}

function stripHTML(path, failed) {
  const z = zones(path).slice().reverse();
  const w = weakSpot(path);
  const fi = failed ? z.indexOf(failed) : -1;
  const short = n => n.kind === "fuse" ? "Street" : "Branch";
  let h = `<span class="node"><i>🏭</i><small>Substation</small></span>`;
  z.forEach((n, i) => {
    const cls = fi >= 0 ? (i === fi ? "broken" : i > fi ? "dark" : "") : (n === w ? "weak" : "");
    h += `<span class="wire ${cls}" title="${esc(n.friendly)}"></span>`;
    const next = z[i + 1];
    if (next) h += `<span class="node ${fi >= 0 && i >= fi ? "dark" : ""}"><i>⚡</i><small>${short(next)}</small></span>`;
  });
  h += `<span class="node ${fi >= 0 ? "dark" : ""}"><i>🏠</i><small>You</small></span>`;
  return h;
}

function renderRestore() {
  const r = S.data.restoration; if (!r || !r.ok) return;
  if (!S.playing) $("#restoreK").textContent = "If your power goes out";
  $("#restoreV").innerHTML = `About ${dur(r.p50)}<small>most likely</small>`;
  const max = Math.max(r.p90 * 1.15, 24);
  $("#rbar").innerHTML = `<span class="seg" style="left:${r.p10 / max * 100}%;width:${(r.p90 - r.p10) / max * 100}%"></span><span class="mark" style="left:${r.p50 / max * 100}%"></span>`;
  $("#rLo").textContent = `As soon as ${dur(r.p10)}`;
  $("#rHi").textContent = `Up to ${dur(r.p90)}`;
}

function topItems() {
  const items = S.data.prep.items.filter(i => i.phase === "before");
  const rank = { you: 0, home: 1, storm: 2, general: 3 };
  return items.slice().sort((a, b) => (a.priority - b.priority) || (rank[a.source] - rank[b.source])).slice(0, 3);
}
function checkLI(i) {
  const k = i.title, on = S.done.has(k);
  return `<li class="${on ? "done" : ""}"><button class="check ${on ? "on" : ""}" data-k="${esc(k)}" aria-pressed="${on}" aria-label="Mark done">
    ${on ? '<svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>' : ""}</button>
    <span class="check-txt">${esc(i.title)}</span></li>`;
}
function planLI(i) {
  const k = i.title, on = S.done.has(k), open = S.open.has(k), isNew = S.newSet && S.newSet.has(k);
  const flag = i.category === "EMERGENCY PLAN" ? '<span class="flag">Important</span>' : "";
  const because = i.tag ? `<span class="because ${i.source}">Because: ${esc(i.tag)}</span>` : "";
  return `<li class="${on ? "done" : ""} ${open ? "open" : ""} ${isNew ? "new" : ""}"><button class="check ${on ? "on" : ""}" data-k="${esc(k)}" aria-pressed="${on}" aria-label="Mark done">
    ${on ? '<svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>' : ""}</button>
    <button class="p-main" data-k="${esc(k)}" aria-expanded="${open}"><span class="p-title">${isNew ? '<span class="new-badge">NEW</span>' : ""}${flag}${esc(i.title)}</span>
    ${because}<span class="p-more">${esc(i.detail)}<span class="p-why">Why: ${esc(i.why)}</span></span></button><span class="caret" aria-hidden="true">›</span></li>`;
}
function renderTopSteps() { $("#topSteps").innerHTML = topItems().map(checkLI).join(""); }

const chanWord = () => ({ sms: "text", push: "notification", voice: "call", email: "email" }[S.prefs.channel]);
const beforeText = w => w.replace("T-", "").replace(" h", " hours");
function renderAlertMini() {
  const a = S.data.alerts;
  const e1 = a.triggers.some(t => t.id === "E1" && t.status === "ACTIVE");
  $("#alertMini").innerHTML = `<span class="bell">${a.eligible_pre_storm ? "🔔" : "🔕"}</span><span>
    <b>${a.eligible_pre_storm ? "You're set for storm alerts" : "You'll get outage updates"}</b>
    <small>${e1 ? "An AEP agent will call you before the storm" : a.eligible_pre_storm ? `First ${chanWord()} about ${beforeText(a.schedule[0].when)} before` : "We'll text you if your power goes out"}</small></span>`;
  $("#alertMini").onclick = () => go("alerts");
}

function renderPrep() {
  const p = S.data.prep, ph = S.phase;
  $("#planSummary").textContent = p.summary;
  $("#profile").innerHTML = p.profile.map(t => `<span>${esc(t)}</span>`).join("") + `<button class="profile add" id="profAdd">+ Add details</button>`;
  $("#profAdd").onclick = openHousehold;
  $("#planNotice").innerHTML = S.notice || "";
  $("#callout").innerHTML = p.escalate && ph === "before"
    ? `<div class="callout call"><span class="big-ico">📞</span><span><b>We'll call you before the storm.</b> Your backup won't last through a worst-case outage, so an AEP agent will help you plan.</span></div>` : "";
  const items = p.items.filter(i => i.phase === ph);
  const done = items.filter(i => S.done.has(i.title)).length;
  const head = { before: "Before the storm", during: "While the power is out", after: "When the power is back" }[ph];
  const mine = items.filter(i => i.source !== "general"), all = items.filter(i => i.source === "general");
  let html = `<div class="plan-group"><span>${head}</span><span>${done} of ${items.length} done</span></div><div class="progress"><i style="width:${items.length ? done / items.length * 100 : 0}%"></i></div>`;
  if (mine.length) html += `<div class="plan-group"><span>Just for you</span><span>${mine.length}</span></div><p class="section-note">Based on your household, your home's power line and this storm.</p><div class="card"><ul class="plan">${mine.map(planLI).join("")}</ul></div>`;
  if (all.length) html += `<div class="plan-group"><span>For everyone in a storm</span><span>${all.length}</span></div><div class="card"><ul class="plan">${all.map(planLI).join("")}</ul></div>`;
  $("#phaseList").innerHTML = html;
}

function openHousehold() {
  const n = S.needs;
  const chips = [["medical_device", "🫁 Medical equipment"], ["refrigerated_meds", "💊 Fridge medicine"], ["mobility", "♿ Mobility needs"],
    ["older_adult", "🧓 Older adult"], ["infant", "👶 Baby"], ["pets", "🐾 Pets"], ["well_pump", "💧 Well water"], ["sump_pump", "🌊 Sump pump"],
    ["work_from_home", "💻 Work from home"], ["ev", "🔌 Electric car"], ["critical_facility", "🏫 School, clinic or facility"]];
  const devices = ["oxygen concentrator", "CPAP machine", "home dialysis machine", "ventilator", "feeding pump", "other medical device"];
  openSheet("Personalize your plan", `
    <p class="muted">Tap what applies. Your plan updates and the new steps are highlighted. We only use what you tell us, and never guess it from your records.</p>
    <div class="card">
      <div class="people" style="margin-top:0"><span>People at home</span>
        <div class="stepper"><button id="pMinus" aria-label="Fewer people">−</button><b id="pCount">${n.household || 2}</b><button id="pPlus" aria-label="More people">+</button></div></div>
      <div class="chips" id="needChips">${chips.map(([k, l]) => `<button class="chip ${n[k] ? "on" : ""}" data-need="${k}">${l}</button>`).join("")}</div>
      <div class="med" id="medBox" ${n.medical_device ? "" : "hidden"}>
        <label>Which equipment?<select id="device">${devices.map(d => `<option ${n.device_name === d ? "selected" : ""}>${d}</option>`).join("")}</select></label>
        <div class="people"><span>Backup battery lasts</span>
          <div class="stepper"><button id="bMinus" aria-label="Less battery">−</button><b id="bCount">${n.battery_hours ?? 6} h</b><button id="bPlus" aria-label="More battery">+</button></div></div>
      </div>
    </div>
    <div class="card"><div class="card-k">Anything else we should know?</div>
      <form class="free-text" id="freeForm"><input id="freeIn" placeholder="e.g. I work from home and my mom lives with us" autocomplete="off"><button class="btn-dark" type="submit">Add</button></form>
      <div class="heard" id="heard"></div></div>
    <button class="btn-dark" id="hhDone" style="width:100%;padding:14px">Update my plan</button>`);
  const draft = JSON.parse(JSON.stringify(S.needs));
  $("#needChips").onclick = e => {
    const c = e.target.closest(".chip"); if (!c) return;
    const k = c.dataset.need, on = !c.classList.contains("on"); c.classList.toggle("on", on);
    if (k === "medical_device") { draft.medical_device = on; $("#medBox").hidden = !on; if (on) { draft.device_name = $("#device").value; draft.battery_hours = draft.battery_hours ?? 6; } else { delete draft.device_name; delete draft.battery_hours; } }
    else if (k === "critical_facility") { if (on) draft.critical_facility = "facility"; else delete draft.critical_facility; }
    else draft[k] = on;
  };
  $("#device").onchange = e => draft.device_name = e.target.value;
  $("#pMinus").onclick = () => { draft.household = Math.max(1, (draft.household || 2) - 1); $("#pCount").textContent = draft.household; };
  $("#pPlus").onclick = () => { draft.household = Math.min(12, (draft.household || 2) + 1); $("#pCount").textContent = draft.household; };
  $("#bMinus").onclick = () => { draft.battery_hours = Math.max(0, (draft.battery_hours ?? 6) - 1); $("#bCount").textContent = draft.battery_hours + " h"; };
  $("#bPlus").onclick = () => { draft.battery_hours = Math.min(96, (draft.battery_hours ?? 6) + 1); $("#bCount").textContent = draft.battery_hours + " h"; };
  $("#freeForm").onsubmit = async e => {
    e.preventDefault(); const t = $("#freeIn").value.trim(); if (!t) return;
    const r = await api("/api/needs", { text: t });
    if (Object.keys(r.needs).length) {
      Object.assign(draft, r.needs); $("#freeIn").value = "";
      $("#heard").textContent = "Got it: " + Object.keys(r.needs).map(k => (chips.find(c => c[0] === k) || [k, k])[1]).join(", ");
      $$("#needChips .chip").forEach(c => c.classList.toggle("on", !!draft[c.dataset.need]));
      if (draft.medical_device) $("#medBox").hidden = false;
    } else $("#heard").textContent = "Thanks. Nothing there changes your plan, but you can also tell me in the Ask tab.";
  };
  $("#hhDone").onclick = async () => { S.needs = draft; closeSheet(); go("prep"); await refreshRest({ highlight: true }); };
}

function renderAlerts() {
  const a = S.data.alerts, msgs = S.data.messages;
  const e1 = a.triggers.some(t => t.id === "E1" && t.status === "ACTIVE");
  const reason = a.reasons.find(r => r.rule === "A2") ? "because of the need you told us about"
    : a.eligible_pre_storm ? `because your outage risk is ${S.data.risk.band.toLowerCase()}` : "";
  $("#alertHero").className = `card alert-hero ${a.eligible_pre_storm ? "" : "no"}`;
  $("#alertHero").innerHTML = `<span class="bell">${a.eligible_pre_storm ? "🔔" : "🔕"}</span><div>
    <b>${a.eligible_pre_storm ? "You qualify for storm alerts" : "Outage updates only"}</b>
    <p>${a.eligible_pre_storm ? `We'll warn you before the storm ${reason}.` : "Your risk is low, so there's no pre-storm warning. You'll still hear from us if your power goes out."}
    ${e1 ? "<br><b style='font-size:14px;color:#BF3A2B'>📞 An AEP agent will also call you before the storm.</b>" : ""}</p></div>`;
  const pre = a.schedule.find(s => s.what === "Pre-storm alert");
  const whens = [
    pre ? `${beforeText(pre.when)} before the storm` : "Before the storm (only if your risk goes up)",
    "Within 15 minutes of an outage", "If the estimate changes by 2+ hours", "When your power is back",
  ];
  const titles = ["Storm heading your way", "Your power is out", "New estimate", "Power is back"];
  $("#msgTimeline").innerHTML = msgs.map((m, i) => `<li style="${i === 0 && !pre ? "opacity:.55" : ""}"><div class="when">${whens[i]}</div>${notifHTML(titles[i], m.text, "")}</li>`).join("");
}
function renderLive() {
  const ch = S.prefs.channel;
  if (ch === "push") {
    const perm = "Notification" in window ? Notification.permission : "unsupported";
    $("#liveTitle").textContent = "Notifications on this phone";
    $("#liveInput").innerHTML = `<div class="toggle-row" style="border-top:0;padding-bottom:0"><span>Storm alerts</span>
      <label class="switch"><input type="checkbox" id="permSw" ${perm === "granted" ? "checked" : ""}><span></span></label></div>`;
    $("#liveNote").textContent = perm === "denied" ? "Notifications are blocked. Turn them on in your phone's settings." : "Alerts appear even when Upline is closed.";
    $("#permSw").onchange = async e => {
      if (e.target.checked && "Notification" in window) await Notification.requestPermission().catch(() => {});
      renderLive();
    };
    return;
  }
  const isEmail = ch === "email";
  $("#liveTitle").textContent = isEmail ? "Your email address" : "Your mobile number";
  $("#liveInput").innerHTML = `<input class="live-in" id="contactIn" type="${isEmail ? "email" : "tel"}" autocomplete="off"
    placeholder="${isEmail ? "name@example.com" : "(540) 555-0123"}" value="${esc(isEmail ? S.contact.email : S.contact.phone)}">`;
  $("#contactIn").oninput = e => { if (isEmail) S.contact.email = e.target.value; else S.contact.phone = e.target.value; };
  $("#liveNote").textContent = ch === "voice" ? "We'll call this number and read your alert aloud. We only use it for storm alerts."
    : "We only use this to send your storm alerts.";
}

async function sysNotify(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted") return false;
  try { const reg = await navigator.serviceWorker.ready; await reg.showNotification(title, { body, icon: "icon-192.png", badge: "icon-192.png", tag: "upline-" + Date.now() }); return true; }
  catch (e) { try { new Notification(title, { body, icon: "icon-192.png" }); return true; } catch (e2) { return false; } }
}

async function deliver(title, text, opts = {}) {
  push(title, text);
  const ch = S.prefs.channel, st = S.meta.channels || {};
  if (ch === "push") return { ok: await sysNotify(title, text.replace(/^Upline:\s*/, "")), channel: "push" };
  if (ch === "voice" && !opts.call) return { ok: false, skipped: true };
  const to = ch === "email" ? S.contact.email : S.contact.phone;
  if (!st[ch] || !to) return { ok: false, preview: true };
  try { return await api("/api/send", { channel: ch, to, messages: [{ title, text }] }); }
  catch (e) { return { ok: false, error: "Couldn't reach Upline's server." }; }
}

function notifHTML(title, text, when = "now") {
  return `<div class="notif"><div class="notif-h"><svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#102A33"/><path d="M32 10v14M32 24l-10 10h20L32 24M32 34v12M22 54h20M32 46v8" fill="none" stroke="#F2B33D" stroke-width="5" stroke-linecap="round"/></svg><b>Upline</b><span>${when}</span></div>
  <div class="notif-t">${esc(title)}</div><p>${esc(text.replace(/^Upline:\s*/, ""))}</p></div>`;
}

function openSheet(title, html, tall = false) {
  $("#sheetTitle").textContent = title; $("#sheetBody").innerHTML = html;
  $("#sheet").classList.toggle("tall", tall);
  $("#sheet").hidden = false; $("#scrim").hidden = false; $("#sheetBody").scrollTop = 0;
}
function closeSheet() { $("#sheet").hidden = true; $("#scrim").hidden = true; }

function bandColor(p) { return BAND[p < .1 ? "Low" : p < .3 ? "Elevated" : p < .6 ? "High" : "Severe"].color; }

function openPath() {
  const r = S.data.risk, w = weakSpot(r.path);
  const icon = n => ({ breaker: "🏭", recloser: "⚡", sectionalizer: "⚡", fuse: "⚡", transformer: "🔋", step: "🔋", home: "🏠" }[n.kind]);
  const items = r.path.slice().reverse().map(n => `<li class="${n === w ? "weak" : ""}" style="--wire:${n.zone_p != null ? bandColor(n.zone_p) : "#D6DFDD"}">
      <span class="pi">${icon(n)}</span>
      <span><b>${esc(n.friendly)}${n === w ? '<span class="weak-tag">Weak spot</span>' : ""}</b><small>${esc(n.fdetail)}</small></span>
      <span class="share">${n.share != null && n.share >= 0.01 ? pct(n.share) : ""}</span></li>`).join("");
  const hist = zones(r.path).reduce((s, n) => s + (n.history || 0), 0);
  const parts = w.fdetail.split(" · ");
  openSheet("Your power's path", `
    <p class="muted">Electricity reaches your home along this exact path. If anything on it breaks, your power goes out. Damage on other streets usually won't affect you.</p>
    <ul class="path-list">${items}</ul>
    <p class="small muted" style="text-align:right;margin-top:-4px">% = share of your outage risk</p>
    <div class="card"><b>Why is the ${esc(w.friendly.toLowerCase())} the weak spot?</b><p class="muted" style="margin-top:4px">It has ${esc(parts[1] || "")} and ${esc(parts[0].toLowerCase())}. In past storms, long overhead lines like this, especially in rural and wooded areas, were damaged most often.${hist ? ` AEP has ${hist} damage report${hist > 1 ? "s" : ""} on your path since 2022.` : ""}</p></div>`);
}

function openWhatIf() {
  const base = S.base;
  const segs = (id, opts, cur) => `<div class="seg" id="${id}">${opts.map(([v, l]) => `<button data-v="${v}" class="${String(cur) === String(v) ? "on" : ""}">${l}</button>`).join("")}</div>`;
  openSheet("What could change this?", `
    <div class="wi-result"><div class="card-k">If your power goes out, it would be back in</div><div class="restore-v" id="wiV"></div><div class="wi-delta" id="wiD"></div></div>
    <div class="wi-row"><div class="card-k">Repair crews</div>${segs("wiCrew", [[60, "Fewer"], [100, "Usual"], [140, "More"]], S.sc.crew_pct)}</div>
    <div class="toggle-row"><span>Help from other utilities after a day</span><label class="switch"><input type="checkbox" id="wiAid" ${S.sc.mutual_aid_pct ? "checked" : ""}><span></span></label></div>
    <div class="wi-row"><div class="card-k">Blocked roads and hard-to-reach spots</div>${segs("wiRoad", [["clear", "Few"], ["usual", "Some"], ["many", "Many"]], S.access)}</div>
    <div class="wi-row"><div class="card-k">Damage crews find</div>${segs("wiDmg", [[0.7, "Less"], [1, "As expected"], [1.5, "More"]], S.sc.extra_damage)}</div>
    <p class="muted small" id="wiTip"></p>`);
  const upd = async () => {
    $("#wiV").textContent = "…";
    const d = await refreshRest(), r = d.restoration;
    $("#wiV").textContent = `${dur(r.p10)} – ${dur(r.p90)}`;
    const delta = r.p50 - base.p50;
    $("#wiD").className = `wi-delta ${delta > 1 ? "worse" : delta < -1 ? "better" : ""}`;
    $("#wiD").textContent = Math.abs(delta) < 1 ? `Most likely about ${dur(r.p50)}, same as the forecast` : `Most likely about ${dur(r.p50)}: ${dur(Math.abs(delta))} ${delta > 0 ? "longer" : "sooner"} than the forecast`;
  };
  const tip = { crews: "how many repair crews are available", severity: "how strong the storm turns out", access: "blocked roads and hard-to-reach repairs", aid: "help from other utilities" };
  const top = (base.drivers || [])[0];
  if (top) $("#wiTip").textContent = `For your home, the biggest factor is ${tip[top.key]}. ` + ((Math.abs(top.worse) + Math.abs(top.better)) < 4 ? "Your line is near the front of the repair line, so most changes won't move it much." : "");
  const hook = (id, f) => $("#" + id).onclick = e => { const b = e.target.closest("button"); if (!b) return; segOn("#" + id, b); f(b.dataset.v); upd(); };
  hook("wiCrew", v => S.sc.crew_pct = +v);
  hook("wiRoad", v => S.access = v);
  hook("wiDmg", v => S.sc.extra_damage = +v);
  $("#wiAid").onchange = e => { S.sc.mutual_aid_pct = e.target.checked ? 50 : 0; S.sc.mutual_aid_hours = 24; upd(); };
  upd();
}

function openStorm() {
  const opts = S.meta.presets.map(p => {
    const s = STORMS[p.id];
    return `<button class="storm-opt ${S.preset === p.id ? "on" : ""}" data-p="${p.id}"><span>${s.ico}</span><span><b>${s.title.replace(" expected", "")}</b><small>${s.like}</small></span></button>`;
  }).join("");
  openSheet("Which storm?", `
    <p class="muted">Pick a storm to see how it would affect your home.</p>
    <div class="storm-opts" id="stormOpts">${opts}
      <button class="storm-opt ${S.preset === "live" ? "on" : ""}" id="liveOpt"><span>📡</span><span><b>Use today's real forecast</b><small id="liveSmall">${S.preset === "live" ? esc(S.liveNote) : "Live weather for the Roanoke Valley"}</small></span></button>
    </div>
    <div class="range-row"><div class="card-k">Storm strength</div><input type="range" id="sevR" min="0.02" max="2.5" step="0.01" value="${S.sc.severity}" aria-label="Storm strength"><div class="lbls"><span>Weaker</span><span>Feb 2025</span><span>Stronger</span></div></div>
    <div class="wi-row"><div class="card-k">Arrives in</div><div class="seg" id="hrsSeg">${[6, 12, 24, 48].map(h => `<button data-h="${h}" class="${S.sc.hours_to_storm === h ? "on" : ""}">${h} hours</button>`).join("")}</div></div>`);
  $("#stormOpts").onclick = e => {
    const b = e.target.closest(".storm-opt"); if (!b || b.id === "liveOpt") return;
    const p = S.meta.presets.find(x => x.id === b.dataset.p);
    S.preset = p.id; S.sc.severity = p.severity; S.sc.hazard = p.hazard; $("#sevR").value = p.severity;
    $$(".storm-opt").forEach(x => x.classList.toggle("on", x === b)); stormChanged();
  };
  $("#liveOpt").onclick = liveForecast;
  $("#sevR").oninput = e => { S.sc.severity = +e.target.value; S.preset = "custom"; $$(".storm-opt").forEach(x => x.classList.remove("on")); stormChangedSoon(); };
  $("#hrsSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; segOn("#hrsSeg", b); S.sc.hours_to_storm = +b.dataset.h; stormChanged(); };
}
let stT; const stormChangedSoon = () => { clearTimeout(stT); stT = setTimeout(stormChanged, 300); };
async function stormChanged() { renderStorm(); await load(); }

async function liveForecast() {
  $("#liveSmall").textContent = "Checking today's forecast…";
  try {
    const u = "https://api.open-meteo.com/v1/forecast?latitude=37.27&longitude=-79.94&hourly=wind_gusts_10m,precipitation,temperature_2m,weather_code&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=3&timezone=America%2FNew_York";
    const h = (await (await fetch(u)).json()).hourly;
    const gust = Math.max(...h.wind_gusts_10m);
    let ice = 0, rain = 0;
    h.weather_code.forEach((c, i) => { const p = h.precipitation[i] || 0; rain += p; if (c === 66 || c === 67 || (h.temperature_2m[i] <= 0.5 && p > 0 && c >= 51 && c <= 67)) ice += p * 0.6; });
    const sw = Math.max(0, (gust - 35) / 25) ** 3 * 0.25, si = (ice / 0.5) ** 2;
    S.sc.severity = +Math.min(2.5, Math.max(0.02, sw + si + (rain > 3 ? 0.05 : 0))).toFixed(2);
    S.sc.hazard = si > sw ? "ice" : rain > 2 ? "tropical" : "wind";
    S.preset = "live";
    S.liveNote = `Gusts up to ${Math.round(gust)} mph${ice > 0.01 ? `, ${ice.toFixed(2)}" ice` : ""}, ${rain.toFixed(1)}" rain`;
    $("#liveSmall").textContent = S.liveNote; $("#sevR").value = S.sc.severity;
    $$(".storm-opt").forEach(x => x.classList.toggle("on", x.id === "liveOpt"));
    stormChanged();
  } catch (e) { $("#liveSmall").textContent = "Couldn't get the forecast. Check your internet connection."; }
}

function openSafety() {
  const items = S.data.prep.items.filter(i => i.phase === "safety");
  openSheet("Stay safe", `<div class="card" style="background:#FBEDEA;border-color:#F0BDB7"><b>See a downed wire? Call 911.</b><p class="muted" style="margin-top:4px">Then report it to AEP. Stay at least 30 feet away and treat every wire as live.</p></div>
    ${items.slice(1).map(i => `<div class="card"><b>${esc(i.title)}</b><p class="muted small" style="margin-top:4px">${esc(i.detail)} ${esc(i.why)}</p></div>`).join("")}`);
}

function openRules() {
  const plain = {
    A1: "Homes with higher risk get a warning before the storm.", A2: "Anyone with a medical, mobility or facility need gets a warning, whatever their risk.",
    A3: "Everyone gets outage, new-estimate and power-back messages.", E1: "If medical backup won't last through a worst-case outage, a person calls.",
    E2: "We only send a new estimate if it changes by more than 2 hours.", E3: "Critical facilities out over 4 hours go to an AEP account manager.",
    E4: "If the forecast gets worse, we warn you again.", E5: "Mention a downed wire, sparks or fire and you get safety steps and a person right away.",
    E6: "When we're not confident, we don't send exact times.",
  };
  openSheet("How alerts work", `<div class="card"><ul class="promises">${S.data.alerts.rules.map(r => `<li><span style="font:700 13px var(--body);color:#11766F;min-width:24px">${r.id}</span><span>${plain[r.id] || esc(r.rule)}</span></li>`).join("")}</ul></div>
    <p class="muted small" style="margin-top:10px">Quiet hours: no messages from 10 pm to 7 am, except safety, medical and critical-facility alerts.</p>`);
}

function openReport() {
  const opts = [["pole", "🪵", "Broken pole"], ["wire", "〰️", "Wire down"], ["tree", "🌳", "Tree on a line"], ["transformer", "🔋", "Damaged transformer"], ["service", "🏠", "Line to my house is down"]];
  openSheet("Report damage", `<div class="card" style="background:#FBEDEA;border-color:#F0BDB7"><b>Stay at least 30 feet away. Call 911 if a wire is down.</b></div>
    <p class="muted" style="margin-top:10px">What can you see from a safe distance? We'll add it to the repair plan and update your estimate.</p>
    <div class="dmg-grid" id="dmgGrid">${opts.map(([k, i, l]) => `<button class="dmg ${S.reports.includes(k) ? "on" : ""}" data-r="${k}"><span>${i}</span>${l}</button>`).join("")}</div>
    <div id="dmgOut" style="margin-top:12px"></div>`);
  $("#dmgGrid").onclick = async e => {
    const b = e.target.closest(".dmg"); if (!b) return;
    b.classList.add("on"); if (!S.reports.includes(b.dataset.r)) S.reports.push(b.dataset.r);
    $("#dmgOut").innerHTML = `<p class="muted">Updating your estimate…</p>`;
    const d = await api("/api/report", { pid: S.pid, scenario: scenario(), needs: S.needs, lang: S.lang, reports: S.reports });
    const delta = d.after.p50 - d.before.p50;
    const cls = { pole: "pole", wire: "primary_wire", tree: "primary_wire", transformer: "transformer", service: "secondary_wire" }[b.dataset.r];
    const asm = S.meta.model.labor.assemblies[cls];
    const partName = { "Pole": "new pole", "Crossarm": "crossarm", "Insulator": "insulators", "Pin": "pins", "Guying": "guy wire", "Grounding": "grounding",
      "Dead-End": "dead-ends", "Connector": "connectors", "Secondary Conductor Attachment": "wire attachments", "Service": "service line",
      "Fuse Cutout": "fuse", "Recloser": "recloser", "Switch": "switch", "Transformer": "transformer", "Equipment Lead": "equipment leads", "Bracket": "bracket" };
    const parts = asm ? asm.parts.map(p => `<li>${p.qty > 1 ? p.qty + " " : ""}${partName[p.cu] || p.cu.toLowerCase()}</li>`).join("") : "";
    $("#dmgOut").innerHTML = `<div class="card"><b>Thanks, the crew will know about it.</b><p class="muted" style="margin-top:4px">Your estimate is now about <b>${dur(d.after.p50)}</b> (was ${dur(d.before.p50)}).${Math.abs(delta) > 2 ? " We've sent you an updated estimate." : ""}${delta > 6 ? " Crews fix the lines that serve the most homes first, so a repair near a few homes can wait longer." : ""}</p>
      ${asm ? `<p class="small" style="margin-top:10px"><b>What crews will likely replace</b> <span class="pill fact">AEP labor standards</span></p><ul class="parts">${parts}</ul>
      <p class="muted small" style="margin-top:6px">About ${Math.round(asm.direct_hours * 10) / 10} hours of hands-on work, or ${Math.round(asm.crew_hours)} hours including travel and setup.</p>` : ""}</div>`;
    S.data.restoration = d.after; renderRestore();
    if (Math.abs(delta) > 2) push("New estimate", d.message.text);
  };
}

function openSettings() {
  openSheet("Settings", `
    <div class="card">
      <div class="toggle-row" style="border-top:0"><span><b>Battery saver</b><br><small class="muted">Dark, simple screens to save your phone during an outage</small></span><label class="switch"><input type="checkbox" id="setSaver" ${$("#phone").classList.contains("saver") ? "checked" : ""}><span></span></label></div>
      <div class="toggle-row"><span><b>Read answers aloud</b></span><label class="switch"><input type="checkbox" id="setSpeak" ${S.speak ? "checked" : ""}><span></span></label></div>
    </div>
    <button class="btn-line" id="setHome" style="margin-top:4px">Change home</button>
    <button class="btn-line" id="setQR" style="margin-top:10px">Open on another phone</button>
    <button class="link center" id="setTrust">How does Upline know this?</button>`);
  $("#setSaver").onchange = e => $("#phone").classList.toggle("saver", e.target.checked);
  $("#setSpeak").onchange = e => S.speak = e.target.checked;
  $("#setHome").onclick = openHomePicker;
  $("#setQR").onclick = openQR;
  $("#setTrust").onclick = openTrust;
}

function openHomePicker() {
  openSheet("Choose a home", `<div class="homes">${homeOptions()}</div><button class="btn-line" id="pickMap2">Pick a spot on the map</button>
  <button class="btn-line" id="pickRand" style="margin-top:10px">Surprise me</button>`);
  $("#pickMap2").onclick = openMap;
  $("#pickRand").onclick = async () => { closeSheet(); const r = await api("/api/random"); selectPid(r.pid); };
}

async function openMap() {
  openSheet("Pick your area", `
    <div class="map-area">📍 Roanoke Valley, Virginia</div>
    <p class="muted small">Colored areas are the ~117,600 homes in AEP's challenge data. Areas outside it weren't included, so they stay uncolored. Tap a colored area to pick a home there.</p>
    <div class="map-full" id="mapBox"><div id="leafMap"></div></div>
    <div class="legend"><b style="margin-right:2px">Chance of losing power:</b>${Object.values(BAND).map(v => `<span><i style="background:${v.color}"></i>${v.word}</span>`).join("")}</div>
    <p class="map-note">Shown by neighborhood (about 400 m). Areas with fewer than 10 homes are hidden to protect privacy.</p>`, true);
  const layer = await api("/api/map", { scenario: scenario() });
  const ok = await leafletMap(layer).catch(e => { console.warn(e); return false; });
  if (!ok) { $("#mapBox").innerHTML = `<canvas id="mapC"></canvas>`; drawMap($("#mapC"), layer); }
}
function loadLeaflet() {
  if (window.L) return Promise.resolve(true);
  return new Promise(res => {
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"; document.head.appendChild(css);
    const s = document.createElement("script"); s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    s.onload = () => res(true); s.onerror = () => res(false); document.head.appendChild(s);
    setTimeout(() => res(!!window.L), 4000);
  });
}
async function leafletMap(layer) {
  if (!(await loadLeaflet()) || !window.L) return false;
  const G = layer.grid;
  const map = L.map("leafMap", { zoomControl: true, attributionControl: true, preferCanvas: true, minZoom: 9, maxZoom: 15 });
  let loaded = 0, failed = 0, switched = false;
  const esri = (name) => L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${name}/MapServer/tile/{z}/{y}/{x}`,
    { maxNativeZoom: 16, attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors" });
  const base = esri("World_Light_Gray_Base").addTo(map);
  const labels = esri("World_Light_Gray_Reference");
  base.on("tileload", () => loaded++).on("tileerror", () => {
    failed++;
    if (failed > 3 && !loaded && !switched) {
      switched = true; map.removeLayer(base);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" })
        .on("tileload", () => loaded++).addTo(map);
    }
  });
  const renderer = L.canvas({ padding: 0.3 });
  const pts = [];
  layer.cells.forEach(([gx, gy, n, p]) => {
    const ll = [gy * G, gx * G]; pts.push(ll);
    L.circle(ll, { renderer, radius: 260, stroke: false, fillColor: bandColor(p), fillOpacity: Math.min(.62, .3 + n / 300) }).addTo(map)
      .on("click", async () => { const q = await api(`/api/random?cell=${gx},${gy}`); closeSheet(); selectPid(q.pid); });
  });
  labels.addTo(map);
  const bounds = L.latLngBounds(pts);
  map.fitBounds(bounds, { padding: [8, 8] });
  map.setMaxBounds(bounds.pad(0.6));
  await wait(2500);
  if (!loaded) { map.remove(); return false; }   // offline: fall back to the built-in map
  return true;
}
function drawMap(cv, L) {
  const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = Math.round(w * 1.25);
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + "px";
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const G = L.grid; let mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9;
  L.cells.forEach(([x, y]) => { mnx = Math.min(mnx, x); mxx = Math.max(mxx, x); mny = Math.min(mny, y); mxy = Math.max(mxy, y); });
  const k = Math.cos(37.2 * Math.PI / 180), sx = (mxx - mnx + 2) * k, sy = mxy - mny + 2, s = Math.min(w / sx, h / sy);
  const ox = (w - sx * s) / 2, oy = (h - sy * s) / 2;
  const px = x => ox + (x - mnx + 1) * k * s, py = y => h - (oy + (y - mny + 1) * s);
  const cs = Math.max(2, k * s);
  ctx.fillStyle = "#F4F6F5"; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(17,118,111,.22)"; ctx.lineWidth = 1;
  S.meta.map.backbone.forEach(l => { ctx.beginPath(); l.forEach(([a, b], i) => i ? ctx.lineTo(px(a / G), py(b / G)) : ctx.moveTo(px(a / G), py(b / G))); ctx.stroke(); });
  L.cells.forEach(([x, y, n, p]) => { ctx.fillStyle = bandColor(p); ctx.globalAlpha = Math.min(.6, .28 + n / 300); ctx.beginPath(); ctx.arc(px(x), py(y), Math.max(2.2, s * .78), 0, 7); ctx.fill(); });
  ctx.globalAlpha = 1;
  ctx.font = "700 12px 'Public Sans', system-ui, sans-serif"; ctx.textAlign = "center";
  S.meta.map.towns.slice(0, 10).forEach(([name, lon, lat], i) => {
    const X = px(lon / G), Y = py(lat / G);
    ctx.lineWidth = 3.5; ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.strokeText(name, X, Y);
    ctx.fillStyle = "#102A33"; ctx.fillText(name, X, Y);
  });
  cv.onclick = async e => {
    const r = cv.getBoundingClientRect(), gx = Math.round((e.clientX - r.left - ox) / (k * s) + mnx - 1), gy = Math.round((h - (e.clientY - r.top) - oy) / s + mny - 1);
    let best = null, bd = 1e9; L.cells.forEach(c => { const d = (c[0] - gx) ** 2 + (c[1] - gy) ** 2; if (d < bd) { bd = d; best = c; } });
    if (!best || bd > 9) return;
    const q = await api(`/api/random?cell=${best[0]},${best[1]}`); closeSheet(); selectPid(q.pid);
  };
}

function qrSVG(url) { if (!window.qrcode) return ""; const q = qrcode(0, "M"); q.addData(url); q.make(); return q.createSvgTag({ cellSize: 5, margin: 1, scalable: true }); }
function pitchQR() {
  const url = `${S.meta.lan}/?judge=1`;
  const tryIt = () => { const s = qrSVG(url); if (s) { $("#pitchQr").innerHTML = s; $("#pitchUrl").textContent = "Scan to try it on your phone"; } };
  window.qrcode ? tryIt() : window.addEventListener("load", tryIt);
}
async function openQR() {
  const r = await api("/api/random");
  const base = location.protocol === "https:" ? location.origin : S.meta.lan;
  const url = `${base}/?pid=${r.pid}`;
  openSheet("Open on another phone", `<p class="muted">Scan with another phone. It opens Upline with a random home.</p>
    <div class="qr-box">${qrSVG(url) || "<p>The QR code needs an internet connection.</p>"}</div><p class="muted small" style="text-align:center;word-break:break-all">${esc(url)}</p>`);
}

async function openTrust() {
  const m = S.meta.model;
  const lifts = m.backtests.map(b => { const c = b.calibration; return c[9].obs / Math.max((c[0].obs + c[1].obs + c[2].obs) / 3, 0.002); });
  const lift = Math.round(Math.min(...lifts));
  const bt = m.backtests.find(b => b.test === "ice_feb2025") || m.backtests[0];
  const c = bt.calibration, g5 = [0, 2, 4, 6, 8].map(i => (c[i].obs + c[i + 1].obs) / 2), mx = Math.max(...g5);
  const W = 320, H = 130;
  let bars = g5.map((v, i) => { const bh = Math.max(2, v / mx * 86), x = 14 + i * 62; return `<rect x="${x}" y="${100 - bh}" width="46" height="${bh}" rx="5" fill="${["#2E8B6E", "#8FAE4E", "#C99A1F", "#E0742C", "#BF3A2B"][i]}"/><text x="${x + 23}" y="${95 - bh}" text-anchor="middle" font-size="12" font-weight="700" fill="#102A33">${Math.round(v * 100)}%</text>`; }).join("");
  bars += `<text x="14" y="118" font-size="11" fill="#4A5E64">Lowest risk</text><text x="${W - 4}" y="118" font-size="11" fill="#4A5E64" text-anchor="end">Highest risk</text>`;
  const cal = m.calibration;
  const L2 = 300, H2 = 120, X = d => 10 + d / 8 * (L2 - 20), Y = v => 100 - v * 88;
  const line = `<polyline fill="none" stroke="#11766F" stroke-width="3" points="${cal.observed.map((v, i) => `${X(cal.days[i])},${Y(v)}`).join(" ")}"/>`
    + `<polyline fill="none" stroke="#D99A0B" stroke-width="3" stroke-dasharray="6 4" points="${cal.simulated.map((v, i) => `${X(cal.days[i])},${Y(v)}`).join(" ")}"/>`
    + `<text x="${X(3.4)}" y="${Y(0.28)}" font-size="11" font-weight="700" fill="#11766F">What really happened</text><text x="${X(3.4)}" y="${Y(0.12)}" font-size="11" font-weight="700" fill="#8A5F00">Upline's estimate</text>`
    + `<text x="10" y="116" font-size="11" fill="#4A5E64">Storm day</text><text x="${L2 - 10}" y="116" font-size="11" fill="#4A5E64" text-anchor="end">8 days later</text>`;
  openSheet("How Upline knows", `
    <div class="stats">
      <div class="stat"><b>117,595</b><small>homes mapped to their power lines</small></div>
      <div class="stat"><b>${m.data_notes.damage_records.toLocaleString()}</b><small>real damage reports from AEP</small></div>
      <div class="stat"><b>2</b><small>real storms used to test it</small></div>
    </div>
    <div class="card proof"><h3>It works on storms it hasn't seen</h3>
      <p class="muted small">We trained Upline on one storm, then checked it against a different one.</p>
      <div class="big-claim">Areas it rated riskiest were damaged ${lift}× more often than the safest areas.</div>
      <div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Damage rate by risk group">${bars}</svg></div>
      <p class="muted small">Share of areas actually damaged in the Feb 2025 ice storm, grouped by how risky Upline said they were.</p></div>
    <div class="card proof"><h3>Repair times match reality</h3>
      <p class="muted small">Share of Feb 2025 repairs finished each day: AEP's records vs. Upline's simulation, built from AEP's crew labor hours.</p>
      <div class="chart"><svg viewBox="0 0 ${L2} ${H2}" role="img" aria-label="Restoration curve comparison">${line}</svg></div>
      <p class="muted small">On average within ${Math.round(cal.rmse * 100)} percentage points.</p></div>
    <div class="card"><h3 style="font-size:17px">Your privacy</h3><ul class="promises">
      <li><span>🔒</span><span>No names, addresses or account numbers. Homes get an anonymous ID.</span></li>
      <li><span>🩺</span><span>Health needs are only used if you tell us. We never look them up.</span></li>
      <li><span>🗺️</span><span>Maps show neighborhoods, never individual homes or exact hospital locations.</span></li>
      <li><span>✂️</span><span>If you type a phone number or address in chat, we remove it.</span></li>
      <li><span>🤖</span><span>The AI explains our numbers. It can't make up its own.</span></li>
    </ul></div>
    <div class="card"><h3 style="font-size:17px">What we don't know yet</h3><ul class="promises">
      <li><span>🌳</span><span>Exactly where trees are. We use how rural an area is instead.</span></li>
      <li><span>👷</span><span>Where crews are right now. Times are estimates, not promises.</span></li>
      <li><span>🏭</span><span>Problems on big transmission lines or at substations.</span></li>
    </ul></div>
    <details class="tech"><summary>Technical details</summary>
      <table>${m.backtests.map(b => `<tr><td>Train ${esc(b.train.replace("_", " "))} → test ${esc(b.test.replace("_", " "))}</td><td>AUC ${b.auc.toFixed(2)} (baseline ${b.auc_baseline_customers_only.toFixed(2)})</td><td>Top 20% catches ${pct(b.top20_capture)}</td></tr>`).join("")}</table>
      <h4>Model</h4><ul>
        <li>Poisson damage-rate model per protective section (${m.data_notes.zones.toLocaleString()} fuse, recloser and breaker zones built from matched_upstream.txt), with storm severity as the intercept.</li>
        <li>Home risk = 1 − Π(1 − p) over the sections on its own path, plus its transformer and service drop.</li>
        <li>Restoration: Monte Carlo (160 runs) using STORMS labor hours × 4.5 indirect multiplier, 4-person crews, 16-hour shifts, access adders (${pct(m.access_rate)} observed), step restoration by customers per crew-hour with critical-facility priority. Crews calibrated (≈${cal.crews}) to the observed Feb 2025 curve.</li>
        <li>Features: ${Object.keys(m.coef).map(k => esc(m.friendly[k])).join("; ")}.</li>
        <li>Left out: ${Object.keys(m.excluded_features).map(esc).join("; ")}.</li>
        <li>Damage snapped to sections by same-circuit nearest asset (median ${Math.round(m.data_notes.median_snap_m)} m).</li></ul>
      <h4>Controls</h4><ul><li>PII redaction → safety interrupt → privacy and injection guard → tools → optional LLM → numeric grounding guard.</li>
        <li>Hashed IDs; life-support and THREAT flags never loaded; map cells need ${m.k_anon}+ homes; facilities generalized to ~1 km.</li></ul>
      <h4>Audit trail (latest tool calls)</h4><div class="audit" id="auditBox">Loading…</div>
    </details>`, true);
  const a = await api("/api/audit");
  $("#auditBox").innerHTML = a.events.slice(0, 40).map(e => `<div>${esc(e.t)} <code>${esc(e.tool)}</code> ${esc(e.out)}</div>`).join("") || "No calls yet";
}

function push(title, text) {
  const box = $("#notifs");
  const el = document.createElement("div"); el.innerHTML = notifHTML(title, text); const n = el.firstElementChild;
  box.prepend(n);
  while (box.children.length > 2) box.lastElementChild.remove();
  setTimeout(() => { n.classList.add("leave"); setTimeout(() => n.remove(), 400); }, 4600);
}
function offline() {
  let el = $("#offlineBar");
  if (!el) { el = document.createElement("div"); el.id = "offlineBar"; el.className = "offline-bar"; $("#phone").appendChild(el); }
  el.innerHTML = `Can't connect right now. <button id="retryBtn">Try again</button>`;
  $("#retryBtn").onclick = () => load();
}
function hideOffline() { const el = $("#offlineBar"); if (el) el.remove(); }

async function playStorm() {
  if (S.playing) return;
  const btn = $("#playBtn"), label = $("#playLabel");
  if (btn.dataset.reset) { delete btn.dataset.reset; label.textContent = "Watch the storm play out"; $("#reportBtn").hidden = true; return load(); }
  S.playing = true; btn.disabled = true; go("home");
  const r = await api("/api/playback", { pid: S.pid, scenario: scenario(), needs: S.needs, lang: S.lang });
  const path = S.data.risk.path, failed = zones(path)[r.inference.failed_index] || weakSpot(path);
  const card = $("#riskCard"), titles = ["Storm heading your way", "Your power is out", "New estimate", "Power is back"];
  label.textContent = "Storm in progress…";
  deliver(titles[0], r.steps[0].message.text); await wait(3600);
  card.classList.add("out"); $("#riskTag").textContent = "Simulated";
  $("#riskK").textContent = "Right now"; $("#riskPct").textContent = "Out"; $("#riskWord").textContent = "Power is off";
  $("#dial").innerHTML = `<svg viewBox="0 0 74 50" aria-hidden="true"><text x="37" y="40" text-anchor="middle" font-size="34">🔦</text></svg>`;
  $("#riskWhy").innerHTML = `<b>${r.inference.reports} neighbors</b> reported outages too. Likely cause: damage on your <b>${esc(failed.friendly.toLowerCase())}</b>, which feeds about ${r.inference.affected_homes.toLocaleString()} homes.`;
  $("#sure").textContent = "Simulated storm";
  $("#strip").innerHTML = stripHTML(path, failed);
  $("#restoreK").textContent = "Estimated power back";
  S.data.restoration = r.before; renderRestore();
  deliver(titles[1], r.steps[1].message.text, { call: true }); await wait(4200);
  S.data.restoration = r.after; renderRestore(); $("#reportBtn").hidden = false;
  deliver(titles[2], r.steps[2].message.text); await wait(4200);
  card.classList.remove("out"); card.classList.add("back");
  $("#riskK").textContent = "Right now"; $("#riskPct").textContent = "On"; $("#riskWord").textContent = "Power is back";
  $("#dial").innerHTML = `<svg viewBox="0 0 74 50" aria-hidden="true"><text x="37" y="40" text-anchor="middle" font-size="34">💡</text></svg>`;
  $("#riskWhy").innerHTML = `Crews fixed your ${esc(failed.friendly.toLowerCase())} and everything before it on the line. Still out? Reply OUT and we'll check.`;
  $("#strip").innerHTML = stripHTML(path); $("#reportBtn").hidden = true;
  $("#restoreK").textContent = "Your power was off for about"; $("#restoreV").innerHTML = `${dur(r.after.p50)}<small>in this simulated storm</small>`;
  deliver(titles[3], r.steps[3].message.text);
  S.playing = false; btn.disabled = false; btn.dataset.reset = 1; label.textContent = "Back to the forecast";
}

function addMsg(html, who, cls = "") {
  const d = document.createElement("div"); d.className = `msg ${who} ${cls}`; d.innerHTML = html;
  $("#chatLog").appendChild(d); d.scrollIntoView({ block: "end", behavior: "smooth" }); return d;
}
function botSay(text, kind = "", trace) {
  let h = md(text);
  if (trace && trace.length) h += `<details><summary>Safety checks (${trace.length})</summary><ul>${trace.map(t => `<li><b>${esc(t.control)}:</b> ${esc(t.detail)}</li>`).join("")}</ul></details>`;
  addMsg(h, "bot", kind);
  if (S.speak && "speechSynthesis" in window) {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.replace(/[*_]/g, "").replace(/[\u{1F300}-\u{1FAFF}☀-➿]/gu, ""));
    u.lang = S.lang === "es" ? "es-US" : "en-US"; speechSynthesis.speak(u);
  }
}
async function ask(q) {
  addMsg(esc(q), "user");
  const t = addMsg("…", "bot", "typing");
  try {
    const r = await api("/api/chat", { message: q, pid: S.pid, scenario: scenario(), needs: S.needs, lang: S.lang });
    t.remove(); botSay(r.text, r.kind, r.trace);
    if (r.needs && JSON.stringify(r.needs) !== JSON.stringify(S.needs)) {
      S.needs = { ...S.needs, ...r.needs }; await refreshRest({ highlight: true });
      if (S.notice) addMsg(`I've updated your plan on the <b>Prepare</b> tab.`, "bot");
    }
  } catch (e) { t.remove(); botSay("I can't connect right now. If you see a downed wire, stay 30 feet away and call 911."); }
}
let REC = null;
function listen() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return botSay("Voice needs Chrome, Edge or Safari on a secure (https) connection. You can type your question instead.");
  if (REC) return REC.stop();
  REC = new SR(); REC.lang = S.lang === "es" ? "es-US" : "en-US"; REC.interimResults = true;
  $("#micBtn").classList.add("listening"); $("#micText").textContent = "Listening…";
  let said = "";
  REC.onresult = e => { said = [...e.results].map(x => x[0].transcript).join(""); $("#askInput").value = said; };
  REC.onend = () => { $("#micBtn").classList.remove("listening"); $("#micText").textContent = "Tap to talk"; REC = null; if (said.trim()) { $("#askInput").value = ""; ask(said.trim()); } };
  REC.onerror = () => { $("#micBtn").classList.remove("listening"); $("#micText").textContent = "Tap to talk"; REC = null; };
  REC.start();
}

init().catch(e => { console.error(e); document.body.insertAdjacentHTML("afterbegin", `<p style="padding:14px;background:#FBEDEA">Upline couldn't start: ${esc(e.message)}. Is the server running?</p>`); });
