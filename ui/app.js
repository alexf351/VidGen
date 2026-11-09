/* VidGen editor: a single-page frontend for the local API (server.py). No build step. */
"use strict";

// Fallback prices, used only if /api/config has no "prices" (an older server). They mirror
// config.yaml (fal.* and sume.* image_cost / video_cost_per_second, elevenlabs.cost_per_1k_chars).
const RATES = {
  fal: { image: 0.0398, video: { "480p": 0.1125, "720p": 0.2419 } },
  sume: { image: 0.039, video: { "480p": 0.056246, "720p": 0.12096 } },
  voicePer1k: 0.22,
};
// Upper-bound guess for a full run when a format reports no limits (an older server).
const NEW_RUN_GUESS = { images: 30, sheets: 6, clips: 8, voiceChars: 650 };
const STEPS = ["script", "images", "video", "voice", "assemble"];
const ACTIVE = new Set(["queued", "running"]);

const S = {
  config: null, formats: [], runs: [], jobs: [],
  run: null, runId: null, stamps: {}, selected: new Set(),
  draft: null, draftFor: null, saveErrors: null, afterSave: null,
  provider: "", viewJob: null, viewPinned: false, es: null,
  jobStatus: new Map(), jobsLoaded: false, doctor: null,
};

// ------------------------------------------------------------------ helpers
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") throw new Error("no html");
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);
const usd = (n) => (n == null ? "–" : n < 0.01 && n > 0 ? "<$0.01" : `$${n.toFixed(2)}`);
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const s = (Date.now() - d) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function errText(detail) {
  if (!detail) return "request failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  if (detail.message) return detail.message;
  return JSON.stringify(detail);
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (method !== "GET") {
    opts.headers["content-type"] = "application/json";
    opts.body = JSON.stringify(body ?? {});
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const err = new Error(errText(data && data.detail));
    err.status = res.status; err.detail = data && data.detail;
    throw err;
  }
  return data;
}

function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}`, role: "status" }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "bad" ? 7000 : 4000);
}

function bust(url, runId) {
  if (!url) return null;
  const stamp = S.stamps[runId] || (S.stamps[runId] = Date.now());
  return `${url}${url.includes("?") ? "&" : "?"}t=${stamp}`;
}

// ---------------------------------------------------------------- modal
function confirmDialog({ title, text, rows = [], note, ok = "Run", total }) {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    const close = (v) => { root.replaceChildren(); document.removeEventListener("keydown", key); resolve(v); };
    const key = (e) => { if (e.key === "Escape") close(false); if (e.key === "Enter") close(true); };
    document.addEventListener("keydown", key);
    const okBtn = h("button", { class: "btn primary", onclick: () => close(true) }, ok);
    root.replaceChildren(h("div", { class: "modal-back", onclick: (e) => e.target === e.currentTarget && close(false) },
      h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
        h("h2", {}, title),
        text && h("p", {}, text),
        rows.length ? h("div", { class: "est" },
          rows.map(([k, v]) => h("div", {}, h("span", {}, k), h("span", {}, typeof v === "number" ? usd(v) : v))),
          total !== undefined && h("div", { class: "total" }, h("span", {}, "Estimated"), h("span", {}, usd(total)))) : null,
        note && h("div", { class: "note" }, note),
        h("div", { class: "actions" },
          h("button", { class: "btn ghost", onclick: () => close(false) }, "Cancel"), okBtn))));
    okBtn.focus();
  });
}

// ------------------------------------------------------------ estimates
function providerFor(kind, choice) {
  const c = choice || S.provider;
  if (c) return c;
  return (S.config && S.config.providers.default[kind]) || "fal";
}
function resolution() { return (S.config && S.config.video.resolution) || "480p"; }
function clipSeconds(formatName) {
  const f = S.formats.find((x) => x.name === formatName);
  return (f && f.clip_seconds) || (S.config && S.config.video.clip_seconds) || 4;
}
function prices() {
  const p = S.config && S.config.prices;
  if (!p) return RATES;
  return { fal: { image: p.fal.image, video: p.fal.video_per_second },
           sume: { image: p.sume.image, video: p.sume.video_per_second }, voicePer1k: p.voice_per_1k_chars };
}
function imageRate(choice) { return prices()[providerFor("images", choice)].image; }
function videoRate(choice) {
  const v = prices()[providerFor("video", choice)].video;
  return v[resolution()] ?? Object.values(v)[0];
}
function imageCost(n, choice) { return n * imageRate(choice); }
function clipCost(n, formatName, choice) { return n * clipSeconds(formatName) * videoRate(choice); }
function voiceCost(chars) { return (chars / 1000) * prices().voicePer1k; }

function targetShots(run, step, only) {
  const shots = run.shots;
  const pick = only ? shots.filter((s) => only.includes(s.n)) : shots;
  if (step === "images") return pick.filter((s) => (s.kind === "shot" || s.kind === "montage") && (only || !s.image));
  if (step === "video") return pick.filter((s) => s.kind !== "card" && s.kind !== "app_screen" && s.shot.animate && (only || !s.clip));
  if (step === "voice") return pick.filter((s) => s.kind === "shot" && (s.shot.vo_line || "").trim() && (only || !s.audio));
  return [];
}

function missingSheets(run, shots) {
  const need = new Set(shots.flatMap((s) => s.shot.characters || []));
  return run.characters.filter((c) => need.has(c.id) && !c.sheet).length;
}

function estimateStep(run, step, only) {
  const fmt = run.format;
  if (step === "script") {
    return { rows: [["Claude writes the shot list", "a few cents"]], total: undefined,
      note: run.script ? "This replaces the current script.json (and your edits)." : null };
  }
  const shots = targetShots(run, step, only);
  if (step === "images") {
    const sheets = missingSheets(run, shots);
    const rows = [[`${plural(shots.length, "keyframe")}${sheets ? ` + ${plural(sheets, "sheet")}` : ""} × ${usd(imageRate())} (${providerFor("images")})`,
      imageCost(shots.length + sheets)]];
    return { rows, total: imageCost(shots.length + sheets), count: shots.length + sheets,
      note: sheets ? "Sheets for locked characters with a reference image (Iro) cost nothing; counted anyway." : null };
  }
  if (step === "video") {
    const p = providerFor("video");
    return { rows: [[`${plural(shots.length, "clip")} × ${clipSeconds(fmt)}s × ${usd(videoRate())}/s (${p}, ${resolution()})`, clipCost(shots.length, fmt)]],
      total: clipCost(shots.length, fmt), count: shots.length };
  }
  if (step === "voice") {
    const chars = shots.reduce((a, s) => a + s.shot.vo_line.length, 0);
    return { rows: [[`${plural(shots.length, "line")}, ${chars} characters (ElevenLabs)`, voiceCost(chars)]],
      total: voiceCost(chars), count: shots.length };
  }
  return null;     // assemble / recast: local, free
}

function estimateReroll(run, shot) {
  const sheets = missingSheets(run, [shot]);
  const rows = [[`1 keyframe${sheets ? ` + ${plural(sheets, "sheet")}` : ""} (${providerFor("images")})`, imageCost(1 + sheets)]];
  let total = imageCost(1 + sheets);
  if (shot.shot.animate) {
    rows.push([`1 clip × ${clipSeconds(run.format)}s (${providerFor("video")}, ${resolution()})`, clipCost(1, run.format)]);
    total += clipCost(1, run.format);
  }
  return { rows, total };
}

// Upper bound for a whole video in a format, from its limits: every shot drawn, the most
// animated clips it allows, the longest script it allows (about 6 characters a spoken word).
function formatSize(formatName) {
  const f = S.formats.find((x) => x.name === formatName);
  const L = f && f.limits;
  if (!L) return { ...NEW_RUN_GUESS, guess: true };
  const images = L.story_shots[1] + (L.montage ? L.montage[1] : 0) - (L.cards ? L.cards[0] : 0);
  return { images, sheets: f.locked_cast.length + 2, clips: L.max_animated_shots ?? 8, voiceChars: L.vo_words[1] * 6 };
}
function estimateNew(formatName, choice) {
  const g = formatSize(formatName);
  const rows = [
    ["Script (Claude)", "a few cents"],
    [`up to ${g.images} keyframes + ~${g.sheets} sheets (${providerFor("images", choice)})`, imageCost(g.images + g.sheets, choice)],
    [`up to ${g.clips} clips × ${clipSeconds(formatName)}s (${providerFor("video", choice)}, ${resolution()})`, clipCost(g.clips, formatName, choice)],
    [`up to ~${g.voiceChars} characters of voice`, voiceCost(g.voiceChars)],
  ];
  const total = rows.reduce((a, [, v]) => a + (typeof v === "number" ? v : 0), 0);
  return { rows, total };
}

// ------------------------------------------------------------- actions
function runBusy(runId) {
  return S.jobs.some((j) => j.run_id === runId && ACTIVE.has(j.status));
}

async function submit(promise, label) {
  try {
    const r = await promise;
    toast(`${label}: queued`, "ok");
    await refreshJobs();
    if (r && r.job_id) watchJob(r.job_id, true);
    openDrawer(true);
    return r;
  } catch (e) {
    toast(`${label}: ${e.message}`, "bad");
    return null;
  }
}

function providerBody() { return S.provider || null; }

async function runStep(run, step, only) {
  if (only) {
    const applies = targetShots(run, step, only).map((s) => s.n);
    const skipped = only.filter((n) => !applies.includes(n));
    if (!applies.length) {
      toast(`None of those shots ${step === "video" ? "are animated" : step === "voice" ? "have dialogue" : "have an image"}.`);
      return;
    }
    if (skipped.length) toast(`Skipping ${plural(skipped.length, "shot")} with no ${step === "video" ? "clip" : step === "voice" ? "dialogue" : "image"}: ${skipped.join(", ")}`);
    only = applies;
  }
  const est = estimateStep(run, step, only);
  const what = only ? `${step} for ${only.length === 1 ? "shot" : "shots"} ${only.join(", ")}` : `the ${step} step`;
  if (est) {
    if (est.count === 0 && !only) {
      toast(`Nothing to generate: every ${step === "images" ? "keyframe" : step === "video" ? "clip" : "line"} exists. Select shots to redo them.`);
      return;
    }
    const ok = await confirmDialog({ title: `Run ${what}?`, rows: est.rows, total: est.total, note: est.note,
      text: only ? "The selected shots are generated again." : "Shots that already have output are skipped." });
    if (!ok) return;
  }
  await submit(api("POST", `/api/runs/${encodeURIComponent(run.run_id)}/step`,
    { step, only: only || null, provider: providerBody() }), `${step}`);
}

async function reroll(run, shot) {
  const est = estimateReroll(run, shot);
  const ok = await confirmDialog({ title: `Reroll shot ${shot.n}?`, rows: est.rows, total: est.total,
    text: shot.shot.animate ? "A new keyframe and a new clip." : "A new keyframe." });
  if (!ok) return;
  await submit(api("POST", `/api/runs/${encodeURIComponent(run.run_id)}/reroll`,
    { shot: shot.n, provider: providerBody() }), `reroll shot ${shot.n}`);
}

async function recast(run) {
  const ok = await confirmDialog({ title: "Recast this run?", ok: "Recast",
    text: "Copies the format's current locked-character descriptions into script.json and deletes their stale reference sheets. No API calls; the log lists the shots to regenerate." });
  if (!ok) return;
  await submit(api("POST", `/api/runs/${encodeURIComponent(run.run_id)}/recast`, {}), "recast");
}

// ---------------------------------------------------------------- data
async function loadBasics() {
  const [config, formats] = await Promise.all([api("GET", "/api/config"), api("GET", "/api/formats")]);
  S.config = config; S.formats = formats;
}

async function refreshRuns() {
  try { S.runs = await api("GET", "/api/runs"); } catch (e) { toast(`runs: ${e.message}`, "bad"); }
  renderSidebar();
}

async function loadRun(runId, { keepDraft = true } = {}) {
  try {
    const run = await api("GET", `/api/runs/${encodeURIComponent(runId)}`);
    if (S.runId !== runId) return;
    S.run = run;
    const dirty = S.draft && S.draftFor === runId && draftChanged().size;
    if (!keepDraft || !dirty || S.draftFor !== runId) {
      S.draft = run.script ? structuredClone(run.script) : null;
      S.draftFor = runId;
    }
    renderMain();
  } catch (e) {
    if (S.runId !== runId) return;
    S.run = null;
    $("#main").replaceChildren(h("div", { class: "empty" }, e.status === 404 ? "This run no longer exists." : e.message));
  }
}

async function refreshJobs() {
  let jobs;
  try { jobs = await api("GET", "/api/jobs"); } catch { return; }
  const finished = [];
  for (const j of jobs) {
    const prev = S.jobStatus.get(j.id);
    // A job that was active, or one that started and finished between two polls (after the
    // first load), has just finished.
    if (!ACTIVE.has(j.status) && (prev ? ACTIVE.has(prev) : S.jobsLoaded)) finished.push(j);
    S.jobStatus.set(j.id, j.status);
  }
  S.jobsLoaded = true;
  const busyBefore = S.runId && runBusy(S.runId);
  S.jobs = jobs;
  const busyAfter = S.runId && runBusy(S.runId);
  for (const j of finished) onJobFinished(j);
  if (!S.viewPinned || !S.viewJob) {
    const running = jobs.find((j) => j.status === "running");
    if (running && running.id !== S.viewJob) watchJob(running.id, false);
    else if (!S.viewJob && jobs.length) watchJob(jobs[0].id, false);
  }
  renderDrawer();
  if (busyBefore !== busyAfter && !finished.some((j) => j.run_id === S.runId)) renderMain();
  if (finished.length || jobs.some((j) => ACTIVE.has(j.status) && !S.runs.some((r) => r.run_id === j.run_id))) refreshRuns();
}

function onJobFinished(job) {
  if (job.run_id) S.stamps[job.run_id] = Date.now();
  toast(`${job.action}${job.params && job.params.step ? ` ${job.params.step}` : ""} ${job.status === "done" ? "finished" : "failed"}${job.error ? `: ${job.error}` : ""}`,
    job.status === "done" ? "ok" : "bad");
  if (job.run_id && job.run_id === S.runId) loadRun(S.runId);
}

let pollTimer = null;
function schedulePoll() {
  clearTimeout(pollTimer);
  const busy = S.jobs.some((j) => ACTIVE.has(j.status));
  pollTimer = setTimeout(async () => { await refreshJobs(); await refreshOpenRun(); schedulePoll(); }, busy ? 1500 : 5000);
}

// While a job works on the open run, show new thumbnails / clips / lines as they land. Only
// re-render when the step counts move, so scrolling, hovering and typing are not disturbed.
let lastProgressCheck = 0;
async function refreshOpenRun() {
  if (!S.runId || !S.run || !S.jobs.some((j) => j.run_id === S.runId && j.status === "running")) return;
  if (Date.now() - lastProgressCheck < 3000) return;
  lastProgressCheck = Date.now();
  const key = (steps) => JSON.stringify(Object.values(steps).map((s) => s.done));
  try {
    const runs = await api("GET", "/api/runs");
    const fresh = runs.find((r) => r.run_id === S.runId);
    S.runs = runs; renderSidebar();
    if (fresh && key(fresh.steps) !== key(S.run.steps)) {
      S.stamps[S.runId] = Date.now();
      await loadRun(S.runId);
    }
  } catch { /* next poll */ }
}

// --------------------------------------------------------------- sidebar
function runState(r) {
  if (r.job && ACTIVE.has(r.job.status)) return r.job.status;
  if (r.job && r.job.status === "failed") return "failed";
  if (r.steps.assemble.status === "done") return "done";
  if (r.steps.script.status === "done" && Object.entries(r.steps).every(([k, v]) => k === "script" || v.status !== "done" && v.status !== "partial")) return "script";
  if (Object.values(r.steps).some((v) => v.status === "done" || v.status === "partial")) return "partial";
  return "pending";
}
const STATE_LABEL = { running: "running", queued: "queued", failed: "last job failed", done: "video ready",
  script: "script only", partial: "in progress", pending: "not started" };

function renderSidebar() {
  const nav = $("#runs");
  $("#run-count").textContent = S.runs.length ? S.runs.length : "";
  const pick = $("#runs-select");
  pick.replaceChildren(h("option", { value: "", selected: !S.runId }, S.runs.length ? "Open a run…" : "No runs yet"),
    ...S.runs.map((r) => h("option", { value: r.run_id, selected: r.run_id === S.runId }, `${r.premise.slice(0, 60)} · ${STATE_LABEL[runState(r)]}`)));
  if (!S.runs.length) { nav.replaceChildren(h("div", { class: "empty-side" }, "No runs yet. Make your first video.")); return; }
  nav.replaceChildren(...S.runs.map((r) => {
    const st = runState(r);
    return h("a", { class: `run-item${r.run_id === S.runId ? " active" : ""}`, href: `#/run/${encodeURIComponent(r.run_id)}`,
      title: `${r.premise}\n${STATE_LABEL[st]}` },
      h("div", { class: "premise" }, h("span", { class: `dot ${st}`, "aria-label": STATE_LABEL[st] }), h("span", {}, r.premise || r.run_id)),
      h("div", { class: "meta" }, h("span", {}, r.format), h("span", {}, "·"), h("span", {}, when(r.created_at))));
  }));
}

// ---------------------------------------------------------- studio views
function formatTitle(f) { return f.title || f.name.replace(/_/g, " "); }

// A format with no cover yet gets a quiet stand-in: a dark tint keyed to its name, its initial.
function coverArt(f, big) {
  const hue = [...f.name].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
  return h("div", { class: `cover-art${big ? " big" : ""}`,
    style: `background: radial-gradient(110% 70% at 50% 30%, hsl(${hue} 38% 24%), hsl(${hue} 30% 11%) 72%, #0a0c13)` },
    h("span", { class: "cover-initial" }, formatTitle(f).slice(0, 1)),
    h("span", { class: "cover-none" }, "no cover yet"));
}

function coverImg(f) {
  if (!f.cover) return coverArt(f);
  return h("img", { src: f.cover, alt: "", loading: "lazy" });
}

function renderStudio() {
  const formats = S.formats.filter((f) => !f.error).sort((x, y) => (y.default ? 1 : 0) - (x.default ? 1 : 0));
  const broken = S.formats.filter((f) => f.error);
  const cards = formats.map((f) => {
    const est = estimateNew(f.name, "");
    return h("a", { class: `fcard${f.default ? " default" : ""}`, href: `#/new/${encodeURIComponent(f.name)}`,
      title: f.description },
      h("div", { class: "fcard-img" }, coverImg(f), f.default ? h("span", { class: "fcard-tag" }, "Default") : null),
      h("div", { class: "fcard-body" },
        h("div", { class: "fcard-title" }, formatTitle(f)),
        h("div", { class: "fcard-desc" }, f.description)),
      h("div", { class: "fcard-cost" }, `about ${usd(est.total)} a video`));
  });
  $("#main").replaceChildren(h("div", { class: "view studio" },
    doctorNotice(),
    h("div", { class: "studio-head" },
      h("div", {}, h("h1", {}, "Studio"), h("p", { class: "lede" }, "Pick a format. Each one is a look and a story shape.")),
      h("span", { class: "muted", style: "font-size:12px" }, `${formats.length} formats`)),
    h("div", { class: "fgrid" }, cards),
    broken.length ? h("div", { class: "notice bad", style: "margin-top:18px" },
      h("b", {}, "Formats that did not load"), h("ul", {}, broken.map((f) => h("li", {}, h("b", {}, f.name), ": ", f.error)))) : null));
  if (!S.doctor) loadDoctor();
}

function chips(options, value, onChange, label) {
  const wrap = h("div", { class: "chips", role: "radiogroup", "aria-label": label });
  const draw = (v) => wrap.replaceChildren(...options.map(([val, text, sub]) =>
    h("button", { type: "button", class: `chip${val === v ? " on" : ""}`, role: "radio", "aria-checked": String(val === v),
      onclick: () => { draw(val); onChange(val); } }, text, sub ? h("span", { class: "chip-sub" }, sub) : null)));
  draw(value);
  return wrap;
}

function renderCreate(formatName) {
  const f = S.formats.find((x) => x.name === formatName && !x.error);
  if (!f) { $("#main").replaceChildren(h("div", { class: "empty" }, `No format called "${formatName}". `, h("a", { href: "#/new", class: "muted" }, "Back to Studio"))); return; }
  const st = { provider: "", dry: false };
  const d = S.config.providers.default;
  const premise = h("textarea", { class: "premise-box", id: "f-premise", rows: "6", maxlength: "600",
    placeholder: f.limits && f.limits.narrator ? "A baker's oven dies the day her cake goes viral…"
      : "A laid-off line cook buys a beat-up food truck and nobody shows up on day one…" });
  const count = h("span", { class: "count-note" });
  const costLine = h("div", { class: "cost-big" }); const costSub = h("div", { class: "cost-sub" });
  const keyWarn = h("div", { class: "field-note warn" });
  const go = h("button", { class: "btn primary go", type: "submit" }, "Generate video");
  const update = () => {
    const words = premise.value.trim() ? premise.value.trim().split(/\s+/).length : 0;
    count.textContent = words ? `${words} words` : "One or two sentences is plenty";
    const kinds = new Set([providerFor("images", st.provider), providerFor("video", st.provider)]);
    const missing = [...kinds].filter((p) => !S.config.keys_present[p === "fal" ? "FAL_KEY" : "SUME_API_KEY"]);
    keyWarn.textContent = missing.length ? `No API key set for ${missing.join(", ")}.` : "";
    if (st.dry) {
      costLine.textContent = "a few cents"; costSub.textContent = "Script only. Nothing goes to the image, video or voice providers.";
      go.textContent = "Write the script";
    } else {
      const est = estimateNew(f.name, st.provider);
      costLine.textContent = `up to ${usd(est.total)}`;
      costSub.textContent = est.rows.slice(1).map(([k]) => k).join(" · ");
      go.textContent = "Generate video";
    }
  };
  premise.addEventListener("input", update);

  const L = f.limits || {};
  const details = h("details", { class: "card-sec" },
    h("summary", {}, h("span", { class: "sec-label" }, "Format details"), h("span", { class: "muted" }, "Show")),
    h("dl", { class: "facts" },
      f.duration_target ? [h("dt", {}, "Length"), h("dd", {}, f.duration_target)] : null,
      L.story_shots ? [h("dt", {}, "Shots"), h("dd", {}, `${L.story_shots[0]}-${L.story_shots[1]}${L.montage ? ` + ${L.montage[0]}-${L.montage[1]} montage` : ""}`)] : null,
      L.vo_words ? [h("dt", {}, "Spoken words"), h("dd", {}, `${L.vo_words[0]}-${L.vo_words[1]}${L.narrator ? ", narrated" : ", dialogue only"}`)] : null,
      h("dt", {}, "Clips"), h("dd", {}, `up to ${L.max_animated_shots ?? "?"} × ${f.clip_seconds || 4}s`),
      f.locked_cast.length ? [h("dt", {}, "Cast"), h("dd", {}, f.locked_cast.join(", "))] : null,
      L.cta_caption ? [h("dt", {}, "Ends on"), h("dd", {}, L.cta_caption)] : null),
    f.beats.length ? h("ol", { class: "beat-list" }, f.beats.map((b) => h("li", {}, b))) : null);

  const form = h("form", { class: "create-left", onsubmit: async (e) => {
    e.preventDefault();
    const text = premise.value.trim();
    if (!text) { premise.focus(); toast("Write a premise first.", "bad"); return; }
    if (!st.dry) {
      const est = estimateNew(f.name, st.provider);
      const ok = await confirmDialog({ title: `Generate a ${formatTitle(f)} video?`, rows: est.rows, total: est.total,
        text: "Runs script, images, video, voice and assemble.", ok: "Generate",
        note: "An upper bound from the format's limits; the real cost depends on the shot list. Choose Script only to check it first for a few cents." });
      if (!ok) return;
    }
    go.disabled = true;
    const r = await submit(api("POST", "/api/runs", { premise: text, format: f.name, provider: st.provider || null, dry_run: st.dry }),
      st.dry ? "script" : `${formatTitle(f)} video`);
    go.disabled = false;
    if (r) { await refreshRuns(); location.hash = `#/run/${encodeURIComponent(r.run_id)}`; }
  } },
    h("section", { class: "card-sec" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Premise"), count), premise),
    h("section", { class: "card-sec" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Output")),
      chips([[false, "Full video"], [true, "Script only", "a few cents"]], st.dry, (v) => { st.dry = v; update(); }, "Output")),
    h("section", { class: "card-sec" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Provider")),
      chips([["", "Default", `${d.images} / ${d.video}`], ["fal", "fal"], ["sume", "Sume"]], st.provider, (v) => { st.provider = v; update(); }, "Provider"),
      keyWarn),
    details,
    h("section", { class: "card-sec cost-card" }, h("div", {}, costLine, costSub), go));
  premise.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) form.requestSubmit(); });

  // The example: the format's example video, else its cover, else the stand-in art.
  const frame = h("div", { class: "example-frame" });
  let video = null;
  if (f.example_video) {
    video = h("video", { src: f.example_video, muted: true, loop: true, playsinline: true, autoplay: true, preload: "auto" });
    video.muted = true;
    frame.append(video);
  } else if (f.cover) {
    frame.append(h("img", { src: f.cover, alt: `${formatTitle(f)} example` }));
  } else {
    frame.append(coverArt(f, true));
  }
  if (f.example_video || f.cover) frame.append(h("span", { class: "example-tag" }, "Example"));
  const soundBtn = video ? h("button", { class: "btn small", type: "button", onclick: () => {
    video.muted = !video.muted; if (!video.muted) { video.currentTime = 0; video.play(); }
    soundBtn.textContent = video.muted ? "Play with sound" : "Mute";
  } }, "Play with sound") : null;
  const right = h("section", { class: "create-right" },
    h("div", { class: "sec-label" }, "Your result"),
    h("div", { class: "example-wrap" }, frame,
      soundBtn ? h("div", { class: "example-actions" }, soundBtn) : null,
      h("p", { class: "example-note" }, f.example_video || f.cover
        ? `A finished ${formatTitle(f)}. Your video replaces it once you generate.`
        : `No example yet. Make one, then use "Use as cover" on a shot or "Use as example" on the finished video.`)));

  $("#main").replaceChildren(h("div", { class: "view create" },
    h("a", { class: "back-link", href: "#/new" }, "‹ Studio"),
    h("h1", {}, formatTitle(f)),
    h("p", { class: "lede" }, f.description),
    doctorNotice(),
    h("div", { class: "create-grid" }, form, right)));
  update();
  premise.focus();
  if (!S.doctor) loadDoctor();
}

async function setFormatMedia(run, kind, shotN) {
  const f = S.formats.find((x) => x.name === run.format);
  const title = f ? formatTitle(f) : run.format;
  const ok = await confirmDialog({ title: kind === "cover" ? `Use shot ${shotN} as the ${title} cover?` : `Use this video as the ${title} example?`,
    ok: kind === "cover" ? "Use as cover" : "Use as example",
    text: kind === "cover" ? "It shows on this format's card in the Studio. It replaces the current cover, if any."
      : "It plays on this format's create screen. It replaces the current example, if any." });
  if (!ok) return;
  try {
    await api("POST", `/api/formats/${encodeURIComponent(run.format)}/${kind}`,
      kind === "cover" ? { run_id: run.run_id, shot: shotN } : { run_id: run.run_id });
    S.formats = await api("GET", "/api/formats");
    toast(kind === "cover" ? `Cover set for ${title}` : `Example set for ${title}`, "ok");
  } catch (e) { toast(e.message, "bad"); }
}

function doctorNotice() {
  const box = h("div", { id: "doctor-box" });
  fillDoctor(box);
  return box;
}
function fillDoctor(box) {
  if (!box) return;
  if (!S.doctor) { box.replaceChildren(h("div", { class: "notice info" }, h("span", { class: "spin" }), "  Checking setup…")); return; }
  if (S.doctor.error) { box.replaceChildren(h("div", { class: "notice" }, `Could not run the setup check: ${S.doctor.error}`)); return; }
  const fails = S.doctor.checks.filter((c) => c.status === "FAIL");
  if (!fails.length) { box.replaceChildren(); return; }
  box.replaceChildren(h("div", { class: "notice bad" },
    h("b", {}, `${plural(fails.length, "setup check")} failed`), " (python main.py doctor)",
    h("ul", {}, fails.map((c) => h("li", {}, h("b", {}, c.item), ": ", c.detail)))));
}
async function loadDoctor() {
  try { S.doctor = await api("GET", "/api/doctor"); } catch (e) { S.doctor = { error: e.message }; }
  fillDoctor($("#doctor-box"));
}

// -------------------------------------------------------------- run view
function renderRun() {
  const run = S.run;
  const busy = runBusy(run.run_id);
  const active = S.jobs.find((j) => j.run_id === run.run_id && ACTIVE.has(j.status));
  const d = S.config.providers.default;
  const provSel = h("select", { "aria-label": "Provider for actions", disabled: busy, onchange: (e) => { S.provider = e.target.value; } },
    h("option", { value: "", selected: !S.provider }, `default (${d.images}/${d.video})`),
    h("option", { value: "fal", selected: S.provider === "fal" }, "fal"),
    h("option", { value: "sume", selected: S.provider === "sume" }, "Sume"));
  const lastProv = lastProvider(run.run_id);

  const stepBtns = [];
  STEPS.forEach((step, i) => {
    const st = run.steps[step];
    if (i) stepBtns.push(h("span", { class: "step-arrow" }, "›"));
    stepBtns.push(h("button", { class: "step-btn", disabled: busy || (step !== "script" && !run.script),
      title: `Run the ${step} step`, onclick: () => runStep(run, step) },
      h("span", { class: `dot ${st.status}` }), step,
      st.total > 1 ? h("span", { class: "count" }, `${st.done}/${st.total}`) : null));
  });

  const head = h("header", { class: "run-head" },
    h("h1", { class: "run-title" }, run.premise || run.run_id),
    h("div", { class: "run-sub" },
      h("span", {}, "format ", h("b", {}, run.format)),
      h("span", {}, "provider ", provSel),
      lastProv ? h("span", { class: "dim" }, `last run with ${lastProv}`) : null,
      h("span", { class: "cost", title: run.cost.rows.map((r) => `${r.item}: ${usd(r.usd)}`).join("\n") }, `est. ${usd(run.cost.total)}`),
      h("span", { class: "dim" }, when(run.created_at)),
      busy ? h("span", { class: "busy-note" }, h("span", { class: `dot ${active.status}` }),
        `${active.action}${active.params.step ? ` ${active.params.step}` : ""} ${active.status}…`) : null),
    h("div", { class: "steps" }, stepBtns,
      h("span", { style: "flex:1" }),
      h("button", { class: "btn small ghost", disabled: busy || !run.script, onclick: () => recast(run),
        title: "Apply the format's locked character descriptions to this run" }, "Recast")));

  const body = h("div", { class: "run-body" }, shotsColumn(run, busy), sideColumn(run, busy));
  const main = $("#main");
  const scroll = main.scrollTop;
  main.replaceChildren(head, body);
  main.scrollTop = scroll;
}

function lastProvider(runId) {
  const j = S.jobs.find((x) => x.run_id === runId && x.params && x.params.provider);
  if (!j) return null;
  const p = j.params.provider;
  return p.images && p.video && p.images !== p.video ? `${p.images}/${p.video}` : (p.images || p.video);
}

function shotsColumn(run, busy) {
  const col = h("section", { class: "shots-col", "aria-label": "Shots" });
  if (!run.script) {
    col.append(h("div", { class: "empty" }, busy ? "Writing the script…" : "No script yet. Run the script step to write the shot list."));
    return col;
  }
  if (run.characters.length) {
    col.append(h("div", { class: "panel-title" }, "Cast"),
      h("div", { class: "chars" }, run.characters.map((c) => h("div", { class: "char", title: c.description },
        h("div", { class: "face", style: c.sheet ? `background-image:url("${bust(c.sheet, run.run_id)}")` : "" },
          c.sheet ? null : c.id.slice(0, 1).toUpperCase()), c.id))));
  }
  col.append(selectionBar(run, busy), h("div", { class: "grid" }, run.shots.map((s) => shotCard(run, s, busy))));
  return col;
}

function selectionBar(run, busy) {
  const sel = [...S.selected].sort((a, b) => a - b);
  return h("div", { class: "sel-bar", id: "sel-bar" },
    h("div", { class: "panel-title", style: "margin:0" }, `Shots · ${run.shots.length}`),
    h("span", { style: "flex:1" }),
    sel.length ? [
      h("span", { class: "count" }, `${sel.length} selected`),
      ["images", "video", "voice"].map((step) => h("button", { class: "btn small", disabled: busy,
        onclick: () => runStep(run, step, sel) }, `Redo ${step}`)),
      h("button", { class: "btn small ghost", onclick: () => { S.selected.clear(); renderMain(); } }, "Clear"),
    ] : h("span", { class: "dim", style: "font-size:12px" }, "Select shots to redo them together"));
}

function shotCard(run, s, busy) {
  const shot = s.shot;
  const drawable = s.kind === "shot" || s.kind === "montage";
  const spoken = s.kind === "shot" && (shot.vo_line || "").trim();
  const selected = S.selected.has(s.n);
  const thumb = h("div", { class: "thumb" });
  if (s.kind === "card") {
    thumb.append(h("div", { class: "card-text" }, shot.card));
  } else if (s.kind === "app_screen") {
    thumb.append(h("div", { class: "placeholder" }, "App screen", h("br"), (shot.app_screen || "").split("/").pop()));
  } else if (s.image) {
    thumb.append(h("img", { src: bust(s.image, run.run_id), alt: `Shot ${s.n}`, loading: "lazy" }));
    if (!spoken && shot.caption) thumb.append(h("div", { class: "cap" }, shot.caption));
  } else {
    thumb.append(h("div", { class: "placeholder" }, "No image yet"));
  }
  if (s.clip) {
    let video = null;
    thumb.addEventListener("mouseenter", () => {
      if (!video) { video = h("video", { muted: true, loop: true, playsinline: true, preload: "auto", src: bust(s.clip, run.run_id) }); video.muted = true; thumb.append(video); }
      thumb.classList.add("playing");
      video.play().catch(() => {});
    });
    thumb.addEventListener("mouseleave", () => { thumb.classList.remove("playing"); if (video) video.pause(); });
  }
  thumb.append(h("div", { class: "badges" },
    h("span", { class: "badge n" }, `#${s.n}`),
    s.kind !== "shot" ? h("span", { class: "badge kind" }, s.kind === "app_screen" ? "APP" : s.kind.toUpperCase()) : null,
    shot.animate ? h("span", { class: "badge anim", title: s.clip ? "Animated clip (hover to play)" : "Animated: no clip yet" }, s.clip ? "▶ clip" : "▶ —") : null));
  if (drawable) {
    thumb.append(h("input", { type: "checkbox", class: "sel", checked: selected, "aria-label": `Select shot ${s.n}`,
      onchange: (e) => {
        e.target.checked ? S.selected.add(s.n) : S.selected.delete(s.n);
        e.target.closest(".shot").classList.toggle("selected", e.target.checked);
        const bar = $("#sel-bar");
        if (bar) bar.replaceWith(selectionBar(run, runBusy(run.run_id)));
      } }));
  }
  if (s.image) {
    thumb.append(h("button", { class: "set-cover", title: "Use as this format's cover in the Studio",
      "aria-label": `Use shot ${s.n} as the format cover`, onclick: (e) => { e.stopPropagation(); setFormatMedia(run, "cover", s.n); } }, "★"));
  }
  if (s.audio) {
    let audio = null;
    const btn = h("button", { class: "play-audio", title: "Play line", "aria-label": `Play shot ${s.n} line`,
      onclick: (e) => {
        e.stopPropagation();
        if (!audio) audio = new Audio(bust(s.audio, run.run_id));
        if (audio.paused) { audio.currentTime = 0; audio.play(); btn.textContent = "■"; audio.onended = () => (btn.textContent = "▶"); }
        else { audio.pause(); btn.textContent = "▶"; }
      } }, "▶");
    thumb.append(btn);
  }
  const info = h("div", { class: "shot-info" },
    spoken ? [h("div", { class: "speaker" }, shot.speaker), h("div", { class: "line" }, shot.vo_line)]
      : h("div", { class: "line silent" }, s.kind === "card" ? "time card" : s.kind === "app_screen" ? "real screenshot" :
        shot.caption ? `caption: ${shot.caption}` : "silent"));
  const actions = h("div", { class: "shot-actions" },
    h("button", { disabled: busy || !drawable, title: shot.animate ? "New keyframe and clip" : "New keyframe", onclick: () => reroll(run, s) }, "Reroll"),
    h("button", { disabled: busy || !drawable, title: "Redo the keyframe only", onclick: () => runStep(run, "images", [s.n]) }, "Image"),
    h("button", { disabled: busy || !spoken, title: "Redo the voice line", onclick: () => runStep(run, "voice", [s.n]) }, "Voice"));
  return h("article", { class: `shot${selected ? " selected" : ""}` }, thumb, info, actions);
}

function sideColumn(run, busy) {
  const col = h("aside", { class: "side-col" });
  col.append(h("div", { class: "panel-title" }, "Final video"));
  if (run.final_video) {
    const src = bust(run.final_video, run.run_id);
    col.append(h("video", { class: "player", controls: true, playsinline: true, preload: "metadata", src }),
      h("div", { class: "final-actions" },
        h("a", { class: "btn small", href: src, download: `${run.run_id}.mp4` }, "Download mp4"),
        h("a", { class: "btn small ghost", href: src, target: "_blank", rel: "noopener" }, "Open"),
        h("button", { class: "btn small ghost", onclick: () => setFormatMedia(run, "example") }, "Use as example")));
  } else {
    col.append(h("div", { class: "player-empty" }, run.script ? "Not assembled yet. Run Assemble once images, clips and voice are in." : "No video yet."));
  }
  if (run.cost.rows.length) {
    col.append(h("div", { class: "cost-rows" },
      run.cost.rows.map((r) => h("div", {}, h("span", {}, r.item), h("span", {}, usd(r.usd)))),
      h("div", { class: "total" }, h("span", {}, "estimated so far"), h("span", {}, usd(run.cost.total)))));
  }
  if (run.script) col.append(scriptPanel(run, busy));
  return col;
}

// ----------------------------------------------------------- script panel
function draftChanged() {
  const out = new Set();
  if (!S.run || !S.run.script || !S.draft) return out;
  S.draft.shots.forEach((s, i) => {
    const o = S.run.script.shots[i] || {};
    for (const k of ["vo_line", "speaker", "caption", "card"]) if ((s[k] ?? "") !== (o[k] ?? "")) out.add(s.n);
  });
  return out;
}

function scriptPanel(run, busy) {
  const changed = draftChanged();
  const speakers = run.script.characters.map((c) => c.id);
  const words = S.draft.shots.filter((s) => !s.montage).reduce((a, s) => a + (s.vo_line || "").split(/\s+/).filter(Boolean).length, 0);
  const update = (i, key, value, row) => {
    S.draft.shots[i][key] = value;
    if (key === "vo_line" && !value.trim()) S.draft.shots[i].speaker = "";
    const ch = draftChanged();
    row.classList.toggle("dirty", ch.has(S.draft.shots[i].n));
    saveBtn.disabled = busy || !ch.size;
    topSave.disabled = busy || !ch.size;
    discard.disabled = !ch.size;
    actions.classList.toggle("stuck", ch.size > 0);
    wc.textContent = `${S.draft.shots.filter((s) => !s.montage).reduce((a, s) => a + (s.vo_line || "").split(/\s+/).filter(Boolean).length, 0)} spoken words`;
  };
  const rows = S.draft.shots.map((s, i) => {
    const row = h("div", { class: `srow${changed.has(s.n) ? " dirty" : ""}` });
    const fields = h("div", { class: "fields" });
    if (s.card) {
      fields.append(h("span", { class: "kind" }, "time card"),
        h("input", { type: "text", value: s.card, "aria-label": `Shot ${s.n} card text`, oninput: (e) => update(i, "card", e.target.value, row) }));
    } else if (s.app_screen) {
      fields.append(h("span", { class: "kind" }, "app screen"), h("span", { class: "ro" }, s.app_screen));
    } else if (s.montage) {
      fields.append(h("span", { class: "kind" }, "montage"), h("span", { class: "ro" }, "silent, no caption"));
    } else {
      const sp = h("select", { "aria-label": `Shot ${s.n} speaker`, onchange: (e) => update(i, "speaker", e.target.value, row) },
        h("option", { value: "", selected: !s.speaker }, "— silent —"),
        speakers.map((id) => h("option", { value: id, selected: s.speaker === id }, id)));
      fields.append(
        h("div", { class: "pair" }, sp,
          h("input", { type: "text", value: s.caption || "", placeholder: "caption", "aria-label": `Shot ${s.n} caption`,
            oninput: (e) => update(i, "caption", e.target.value, row) })),
        h("textarea", { rows: "2", placeholder: "no dialogue", "aria-label": `Shot ${s.n} dialogue`,
          oninput: (e) => update(i, "vo_line", e.target.value, row) }, s.vo_line || ""));
    }
    row.append(h("span", { class: "num" }, `#${s.n}`), fields);
    return row;
  });
  const saveBtn = h("button", { class: "btn primary small", disabled: busy || !changed.size, onclick: () => saveScript(run) }, "Save script");
  const discard = h("button", { class: "btn ghost small", disabled: !changed.size,
    onclick: () => { S.draft = structuredClone(run.script); S.saveErrors = null; renderMain(); } }, "Discard");
  const wc = h("span", { class: "word-count" }, `${words} spoken words`);
  const topSave = h("button", { class: "btn primary small", disabled: busy || !changed.size, onclick: () => saveScript(run) }, "Save");
  const panel = h("section", { "aria-label": "Script" },
    h("div", { class: "panel-title" }, h("span", {}, "Script"), topSave),
    h("div", { class: "notice info" }, "Saving changes script.json only. Rerun Voice for changed lines (Images for changed scenes), then Assemble."));
  if (S.afterSave && S.afterSave.run === run.run_id && S.afterSave.voice.length) {
    const ns = S.afterSave.voice;
    panel.append(h("div", { class: "notice" }, `Saved. Lines changed on ${ns.length === 1 ? "shot" : "shots"} ${ns.join(", ")}. `,
      h("button", { class: "btn small", disabled: busy, onclick: () => { S.afterSave = null; runStep(run, "voice", ns); } }, "Redo voice for them")));
  }
  if (S.saveErrors) {
    panel.append(h("div", { class: "notice bad errors" }, h("b", {}, "Not saved: the script does not pass validation"),
      h("ul", {}, S.saveErrors.map((e) => h("li", {}, e)))));
  }
  const actions = h("div", { class: `script-actions${changed.size ? " stuck" : ""}` }, saveBtn, discard, wc);
  panel.append(h("div", { class: "script-list" }, rows), actions);
  return panel;
}

async function saveScript(run) {
  const changed = [...draftChanged()];
  const voice = changed.filter((n) => {
    const a = S.draft.shots.find((s) => s.n === n), b = run.script.shots.find((s) => s.n === n) || {};
    return (a.vo_line || "") !== (b.vo_line || "") && (a.vo_line || "").trim() || (a.speaker !== b.speaker && (a.vo_line || "").trim());
  });
  try {
    await api("PUT", `/api/runs/${encodeURIComponent(run.run_id)}/script`, S.draft);
    S.saveErrors = null;
    S.afterSave = { run: run.run_id, voice };
    toast("Script saved", "ok");
    await loadRun(run.run_id, { keepDraft: false });
  } catch (e) {
    S.saveErrors = (e.detail && e.detail.errors ? e.detail.errors : [e.message])
      .map((m) => m.replace(/shots\[(\d+)\]/g, (_, i) => `shot #${Number(i) + 1}`)
        .replace(/characters\[(\d+)\]/g, (_, i) => `character ${Number(i) + 1}`));
    renderMain();
  }
}

// ---------------------------------------------------------------- drawer
function openDrawer(open) {
  const d = $("#drawer");
  d.classList.toggle("collapsed", !open);
  $("#drawer-toggle").textContent = open ? "▾" : "▴";
  $("#drawer-toggle").setAttribute("aria-expanded", String(open));
  try { localStorage.setItem("vidgen.drawer", open ? "1" : "0"); } catch { /* private mode */ }
  if (open) scrollLog(true);
}

function jobLabel(j) {
  const what = j.action === "step" ? `step ${j.params.step}${j.params.only ? ` (${j.params.only})` : ""}`
    : j.action === "reroll" ? `reroll shot ${j.params.shot}`
    : j.action === "new" ? (j.params.dry_run ? "new (dry run)" : "new video") : j.action;
  return what;
}
function runPremise(runId) {
  const r = S.runs.find((x) => x.run_id === runId);
  return r ? r.premise : runId;
}

function renderDrawer() {
  const running = S.jobs.filter((j) => j.status === "running");
  const queued = S.jobs.filter((j) => j.status === "queued").reverse();
  const recent = S.jobs.filter((j) => !ACTIVE.has(j.status)).slice(0, 12);
  const sum = $("#drawer-summary");
  if (running.length) {
    sum.replaceChildren(h("span", { class: "dot running" }), h("b", {}, jobLabel(running[0])),
      h("span", { class: "muted" }, `· ${runPremise(running[0].run_id)}`),
      queued.length ? h("span", { class: "muted" }, `· ${queued.length} queued`) : null);
  } else if (S.jobs.length) {
    const last = S.jobs[0];
    sum.replaceChildren(h("span", { class: `dot ${last.status === "done" ? "done" : "failed"}` }),
      h("span", { class: "muted" }, `Idle · last: ${jobLabel(last)} ${last.status} ${when(last.finished_at)}`));
  } else {
    sum.replaceChildren(h("span", { class: "muted" }, "No jobs yet"));
  }
  const item = (j) => h("div", { class: `job${j.id === S.viewJob ? " viewing" : ""}`, role: "button", tabindex: "0",
    onclick: () => watchJob(j.id, true), onkeydown: (e) => e.key === "Enter" && watchJob(j.id, true) },
    h("span", { class: `dot ${j.status === "done" ? "done" : j.status}` }),
    h("span", { class: "what" }, jobLabel(j)),
    h("span", { class: "when" }, `${runPremise(j.run_id)} · ${when(j.finished_at || j.started_at || j.created_at)}`),
    j.status === "failed" && j.error ? h("span", { class: "error", title: j.error }, j.error) : null);
  $("#job-list").replaceChildren(...[
    running.length ? [h("div", { class: "job-group" }, "Running"), running.map(item)] : null,
    queued.length ? [h("div", { class: "job-group" }, `Queued · ${queued.length}`), queued.map(item)] : null,
    recent.length ? [h("div", { class: "job-group" }, "Recent"), recent.map(item)] : null,
    !S.jobs.length ? h("div", { class: "empty-side" }, "Jobs you start show up here.") : null,
  ].flat(Infinity).filter(Boolean));
}

function logLine(text) {
  const cls = /^(error:|Traceback|\s*also failed)/.test(text) ? "err" : /^(===|\[assemble\] final)/.test(text) ? "hi" : null;
  return h("div", { class: cls }, text || " ");
}
function nearBottom() { const l = $("#log"); return l.scrollHeight - l.scrollTop - l.clientHeight < 40; }
function scrollLog(force) { const l = $("#log"); if (force || nearBottom()) l.scrollTop = l.scrollHeight; }

async function watchJob(id, pinned) {
  if (S.viewJob === id && S.es) return;
  if (S.es) { S.es.close(); S.es = null; }
  S.viewJob = id; S.viewPinned = !!pinned;
  const log = $("#log");
  log.replaceChildren();
  const j = S.jobs.find((x) => x.id === id);
  const title = $("#log-title");
  const setTitle = (job) => title.replaceChildren(h("span", { class: `dot ${job.status === "done" ? "done" : job.status}` }),
    h("b", {}, jobLabel(job)), h("span", {}, `· ${runPremise(job.run_id)} · ${job.status}`),
    job.run_id ? h("a", { href: `#/run/${encodeURIComponent(job.run_id)}`, class: "muted", style: "margin-left:auto" }, "open run ›") : null);
  if (j) setTitle(j);
  renderDrawer();
  if (j && !ACTIVE.has(j.status)) {
    try {
      const full = await api("GET", `/api/jobs/${encodeURIComponent(id)}`);
      if (S.viewJob !== id) return;
      setTitle(full);
      log.replaceChildren(...full.log.map(logLine));
      if (full.error) log.append(logLine(`error: ${full.error}`));
      scrollLog(true);
    } catch (e) { log.replaceChildren(logLine(`error: ${e.message}`)); }
    return;
  }
  const es = new EventSource(`/api/jobs/${encodeURIComponent(id)}/stream`);
  S.es = es;
  let lines = 0;
  es.addEventListener("log", (e) => {
    const stick = nearBottom();
    log.append(logLine(e.data));
    if (++lines > 4000) log.firstChild.remove();
    if (stick) scrollLog(true);
  });
  es.addEventListener("status", (e) => {
    const st = JSON.parse(e.data);
    setTitle(st);
    if (!ACTIVE.has(st.status)) {
      es.close(); if (S.es === es) S.es = null;   // the server ends the stream; do not let EventSource reconnect
      if (st.error) log.append(logLine(`error: ${st.error}`));
      refreshJobs();
    }
  });
  es.onerror = () => { if (es.readyState === EventSource.CLOSED && S.es === es) S.es = null; };
}

// ---------------------------------------------------------------- router
function route() {
  const m = location.hash.match(/^#\/run\/(.+)$/);
  const runId = m ? decodeURIComponent(m[1]) : null;
  if (runId !== S.runId) { S.selected.clear(); S.saveErrors = null; S.afterSave = null; S.draft = null; S.draftFor = null; S.run = null; }
  S.runId = runId;
  renderSidebar();
  const nf = location.hash.match(/^#\/new\/(.+)$/);
  if (runId) {
    if (!S.run) $("#main").replaceChildren(h("div", { class: "empty" }, h("span", { class: "spin" }), "  Loading…"));
    loadRun(runId);
  } else if (nf) {
    renderCreate(decodeURIComponent(nf[1]));
  } else {
    renderStudio();
  }
  $("#main").focus({ preventScroll: true });
}

function renderMain() {
  if (S.runId && S.run && S.run.run_id === S.runId) renderRun();
}

window.addEventListener("beforeunload", (e) => {
  if (draftChanged().size) { e.preventDefault(); e.returnValue = ""; }
});
window.addEventListener("hashchange", () => {
  route();
});

// ------------------------------------------------------------------ boot
(async function boot() {
  $("#runs-select").addEventListener("change", (e) => {
    location.hash = e.target.value ? `#/run/${encodeURIComponent(e.target.value)}` : "#/new";
  });
  $("#drawer-bar").addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    openDrawer($("#drawer").classList.contains("collapsed"));
  });
  let open = false;
  try { open = localStorage.getItem("vidgen.drawer") === "1"; } catch { /* private mode */ }
  openDrawer(open);
  try {
    await loadBasics();
  } catch (e) {
    $("#main").replaceChildren(h("div", { class: "empty" }, `Could not reach the VidGen server: ${e.message}`));
    return;
  }
  await Promise.all([refreshRuns(), refreshJobs()]);
  route();
  schedulePoll();
  setInterval(renderSidebar, 60000);   // keep "5m ago" fresh
})();
