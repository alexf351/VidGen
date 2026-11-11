/* VidGen editor: a single-page frontend for the local API (server.py). No build step. */
"use strict";

// Fallback prices, used only if /api/config has no "prices" (an older server). They mirror
// config.yaml (fal.* and sume.* image_cost / video_cost_per_second, elevenlabs.cost_per_1k_chars).
const RATES = {
  fal: { image: 0.0398, video: { "480p": 0.1125, "720p": 0.2419 } },
  sume: { image: 0.039, video: { "480p": 0.056246, "720p": 0.12096 } },
  voicePer1k: 0.22,
  talkPerSecond: 0.0562,
  songPerMinute: 0.30,
};
// Upper-bound guess for a full run when a format reports no limits (an older server).
const NEW_RUN_GUESS = { images: 30, sheets: 6, clips: 8, voiceChars: 650 };
const PREMISE_MAX = 2000;                // characters the premise box accepts
const STEPS = ["script", "images", "video", "voice", "assemble"];
const ACTIVE = new Set(["queued", "running"]);

const S = {
  config: null, formats: [], runs: [], jobs: [],
  run: null, runId: null, stamps: {}, selected: new Set(),
  draft: null, draftFor: null, saveErrors: null, afterSave: null,
  provider: "", viewJob: null, viewPinned: false, es: null,
  jobStatus: new Map(), jobsLoaded: false, doctor: null,
  chars: [], charsLoaded: false, storyDraft: null, storyFor: null, storyErrors: null,
  voices: null, voicesError: null, preview: null,
  lookOpen: new Set(),         // shots whose Picture and motion editor is open
  runTab: {},                  // run id -> "shots" | "script": the tab open on that video's page
  studioQuery: "",             // what is typed in the format search box
  screens: [], screenGroups: [],   // the app screenshot library (GET /api/screens)
};
const CODE_STEPS = ["story", "scenes", "voice", "render"];

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

// Line icons, drawn inline (no icon font, no network). icon("check", 14) -> an <svg>.
const ICONS = {
  plus: ["M12 5v14", "M5 12h14"], check: ["M20 6L9 17l-5-5"], x: ["M18 6L6 18", "M6 6l12 12"],
  search: ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.3-4.3"],
  "chevron-left": ["M15 18l-6-6 6-6"], "chevron-up": ["M18 15l-6-6-6 6"], "chevron-down": ["M6 9l6 6 6-6"],
  "arrow-right": ["M5 12h14", "M12 5l7 7-7 7"],
  alert: ["M12 9v4", "M12 17h.01", "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"],
  external: ["M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6", "M15 3h6v6", "M10 14L21 3"],
  download: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "M7 10l5 5 5-5", "M12 15V3"],
  star: ["M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"],
  grid: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"],
  text: ["M4 6h16", "M4 12h16", "M4 18h10"],
  phone: ["M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z", "M11 18h2"],
  play: ["M7 4v16l13-8z"],
};
function icon(name, size = 16) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: "ic" })) svg.setAttribute(k, v);
  for (const d of ICONS[name] || []) { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); svg.append(p); }
  return svg;
}
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
  return (S.config && S.config.providers.default[kind]) || "sume";
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
           sume: { image: p.sume.image, video: p.sume.video_per_second }, voicePer1k: p.voice_per_1k_chars,
           talkPerSecond: p.talking_per_second ?? RATES.talkPerSecond, songPerMinute: p.song_per_minute ?? RATES.songPerMinute };
}
function imageRate(choice) { return prices()[providerFor("images", choice)].image; }
function videoRate(choice) {
  const v = prices()[providerFor("video", choice)].video;
  return v[resolution()] ?? Object.values(v)[0];
}
function imageCost(n, choice) { return n * imageRate(choice); }
function clipCost(n, formatName, choice) { return n * clipSeconds(formatName) * videoRate(choice); }
function voiceCost(chars) { return (chars / 1000) * prices().voicePer1k; }
function talkCost(seconds) { return seconds * prices().talkPerSecond; }
function songCost(seconds) { return (seconds / 60) * prices().songPerMinute; }
// Spoken seconds from words (about 2.6 words a second), for talking-clip estimates.
const talkSecondsOf = (text) => (text || "").split(/\s+/).filter(Boolean).length / 2.6 + 0.3;

function targetShots(run, step, only) {
  const shots = run.shots;
  const pick = only ? shots.filter((s) => only.includes(s.n)) : shots;
  if (step === "images") return pick.filter((s) => drawsImage(s) && (only || !s.image));
  if (step === "video") return pick.filter((s) => s.kind !== "card" && s.kind !== "app_screen" && (s.shot.animate || s.shot.talk) && (only || !s.clip));
  if (step === "voice") return pick.filter((s) => (s.kind === "shot" || s.kind === "letter" || s.kind === "app_screen") && (s.shot.vo_line || "").trim() && (only || !s.audio));
  return [];
}

function drawsImage(s) {
  return (s.kind === "shot" || s.kind === "montage" || s.kind === "flash" || s.kind === "letter") && !!(s.shot.image_prompt || "").trim();
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
    const talking = shots.filter((s) => s.shot.talk), moving = shots.filter((s) => !s.shot.talk);
    const secs = talking.reduce((a, s) => a + talkSecondsOf(s.shot.vo_line), 0);
    const rows = [];
    if (moving.length) rows.push([`${plural(moving.length, "clip")} × ${clipSeconds(fmt)}s × ${usd(videoRate())}/s (${p}, ${resolution()})`, clipCost(moving.length, fmt)]);
    if (talking.length) rows.push([`${plural(talking.length, "talking clip")}, ~${Math.round(secs)}s of speech (fal)`, talkCost(secs)]);
    if (!rows.length) rows.push(["no clips to make", 0]);
    const total = clipCost(moving.length, fmt) + talkCost(secs);
    return { rows, total, count: shots.length,
      note: talking.length ? "Talking clips make their voice line first if it is missing (ElevenLabs, a cent or two)." : null };
  }
  if (step === "voice" && run.song) {
    const secs = run.script.shots.reduce((a, s) => a + talkSecondsOf(s.vo_line), 0) + 4;
    return { rows: [[`one song, ~${Math.round(secs)}s (ElevenLabs Music) + lyric timing`, songCost(secs)]],
      total: songCost(secs), count: 1, note: "A song is one piece: the whole song is made again. Music needs a paid ElevenLabs plan." };
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
  if (shot.shot.talk) {
    const secs = talkSecondsOf(shot.shot.vo_line);
    rows.push([`1 talking clip, ~${Math.round(secs)}s (fal)`, talkCost(secs)]);
    total += talkCost(secs);
  } else if (shot.shot.animate) {
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
  const flashes = L.flashes ? L.flashes[1] : 0;     // flashes are stills: an image each, never a clip
  const images = L.letter ? 4 : L.story_shots[1] + (L.montage ? L.montage[1] : 0) + flashes - (L.cards ? L.cards[0] : 0);
  return { images, sheets: L.letter ? 0 : f.locked_cast.length + 2, clips: L.animate_all ? images - flashes : (L.max_animated_shots ?? 8),
    voiceChars: L.song ? 0 : L.vo_words[1] * 6,
    talkSeconds: L.talking ? L.vo_words[1] / 2.6 : 0,
    songSeconds: L.song ? L.vo_words[1] / 2 + 5 : 0 };
}
function estimateNew(formatName, choice) {
  const g = formatSize(formatName);
  const rows = [
    ["Script (Claude)", "a few cents"],
    [`up to ${g.images} keyframes + ~${g.sheets} sheets (${providerFor("images", choice)})`, imageCost(g.images + g.sheets, choice)],
    g.clips ? [`up to ${g.clips} clips × ${clipSeconds(formatName)}s (${providerFor("video", choice)}, ${resolution()})`, clipCost(g.clips, formatName, choice)] : null,
    g.talkSeconds ? [`up to ~${Math.round(g.talkSeconds)}s of talking clips (lip-synced on fal)`, talkCost(g.talkSeconds)] : null,
    g.songSeconds ? [`a ~${Math.round(g.songSeconds)}s song (ElevenLabs Music)`, songCost(g.songSeconds)] : null,
    g.voiceChars ? [`up to ~${g.voiceChars} characters of voice`, voiceCost(g.voiceChars)] : null,
  ].filter(Boolean);
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
    text: shot.shot.talk ? "A new keyframe and a new talking clip." : shot.shot.animate ? "A new keyframe and a new clip." : "A new keyframe." });
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
  await Promise.all([loadChars(), loadScreens()]);
}
// ------------------------------------------------------------ app screens
// The app screenshot library (app_assets.py): the real screens a video's demo beat can show.
async function loadScreens() {
  try { const r = await api("GET", "/api/screens"); S.screens = r.screens; S.screenGroups = r.groups; }
  catch { S.screens = S.screens || []; S.screenGroups = S.screenGroups || []; }
  const n = $("#screen-count"); if (n) n.textContent = S.screens.length ? String(S.screens.length) : "";
}
function screenFor(path) { return (S.screens || []).find((x) => x.path === path) || null; }
function screenTitle(path) { const e = screenFor(path); return e ? e.title : String(path || "").split("/").pop(); }

// Play a recording over its picture while the pointer is on it.
function hoverPlay(box, src) {
  if (!src) return;
  let video = null;
  box.addEventListener("mouseenter", () => {
    if (!video) { video = h("video", { class: "hover-clip", muted: true, loop: true, playsinline: true, preload: "auto", src }); video.muted = true; box.append(video); }
    box.classList.add("playing"); video.currentTime = 0; video.play().catch(() => {});
  });
  box.addEventListener("mouseleave", () => { box.classList.remove("playing"); if (video) video.pause(); });
}

// The library as groups of tiles. opts: isOn(path), orderOf(path), onPick(entry) for a picker;
// onGone(path) after one of your own screenshots is removed. Returns the element; it redraws itself.
function screenGrid(opts = {}) {
  const box = h("div", { class: "sgroups" });
  let adding = false, removing = null, busy = false, error = "";
  const tile = (e) => {
    const on = opts.isOn ? opts.isOn(e.path) : false;
    const order = on && opts.orderOf ? opts.orderOf(e.path) : 0;
    const pic = h("span", { class: "stile-pic" },
      e.url ? h("img", { src: e.url, alt: "", loading: "lazy" }) : h("span", { class: "stile-none" }, "missing"),
      e.clip_url ? h("span", { class: "stile-moves", title: "A recording: the screen moves in the video" }, icon("play", 11), `${Math.round(e.seconds)}s`) : null,
      on ? h("span", { class: "stile-check" }, order ? String(order) : icon("check", 13)) : null);
    hoverPlay(pic, e.clip_url);
    const body = [
      pic,
      h("span", { class: "stile-title" }, e.title),
      h("span", { class: "stile-shows" }, e.shows || "No description yet")];
    const main = opts.onPick
      ? h("button", { class: `stile${on ? " on" : ""}`, type: "button", title: e.shows || e.title, "aria-pressed": on ? "true" : "false",
        onclick: () => { opts.onPick(e); draw(); } }, body)
      : h("div", { class: "stile", title: e.shows || e.title }, body);
    if (!e.mine) return main;
    if (removing === e.path) {
      return h("div", { class: "stile-wrap" }, main, h("div", { class: "stile-ask" },
        h("span", {}, "Remove it?"),
        h("button", { class: "btn small danger", type: "button", disabled: busy, onclick: async () => {
          busy = true; draw();
          try {
            await api("DELETE", `/api/screens/mine/${encodeURIComponent(e.path.split("/").pop())}`);
            await loadScreens();
            if (opts.onGone) opts.onGone(e.path);
          } catch (err) { toast(err.message, "bad"); }
          busy = false; removing = null; draw();
        } }, "Remove"),
        h("button", { class: "btn small ghost", type: "button", onclick: () => { removing = null; draw(); } }, "Keep")));
    }
    return h("div", { class: "stile-wrap" }, main,
      h("button", { class: "stile-del", type: "button", title: "Remove this screenshot", "aria-label": `Remove ${e.title}`,
        onclick: () => { removing = e.path; draw(); } }, icon("x", 13)));
  };
  const addForm = () => {
    const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,.mov,.mp4,.m4v,.webm", "aria-label": "Screenshot or recording file" });
    const title = h("input", { type: "text", maxlength: "60", placeholder: "Streak screen", "aria-label": "Name" });
    const shows = h("input", { type: "text", maxlength: "240", placeholder: "a 30-day streak with the flame and the week row", "aria-label": "What it shows" });
    const go = h("button", { class: "btn primary small", type: "submit", disabled: busy }, busy ? "Adding…" : "Add screenshot");
    file.addEventListener("change", () => {
      const f = file.files[0];
      if (f && !title.value.trim()) title.value = f.name.replace(/\.[a-z0-9]+$/i, "").replace(/[_-]+/g, " ").slice(0, 60);
    });
    return h("form", { class: "sadd", onsubmit: async (ev) => {
      ev.preventDefault();
      const f = file.files[0];
      if (!f) { error = "Choose a screenshot or a screen recording first."; draw(); return; }
      if (!title.value.trim()) { error = "Give it a short name."; draw(); return; }
      const isVideo = /^video\//.test(f.type) || /\.(mov|mp4|m4v|webm)$/i.test(f.name);
      if (isVideo && f.size > 80 * 1024 * 1024) { error = "That recording is over 80 MB. Trim it on your phone first; a few seconds is all a video uses."; draw(); return; }
      busy = true; error = ""; go.disabled = true; go.textContent = isVideo ? "Adding the recording…" : "Adding…";
      try {
        const added = await api("POST", "/api/screens", { title: title.value, shows: shows.value, [isVideo ? "video" : "image"]: await readFile(f) });
        await loadScreens();
        adding = false;
        toast(`Added ${added.title}`, "ok");
      } catch (err) { error = err.message; }
      busy = false; draw();
    } },
      h("div", { class: "sadd-title" }, "Add your own screenshot or recording"),
      h("label", { class: "sadd-field" }, "A phone screenshot (PNG or JPG), or a screen recording (MP4 or MOV, upright, up to 12 seconds are used)", file),
      h("label", { class: "sadd-field" }, "Name", title),
      h("label", { class: "sadd-field" }, "What it shows, so the script writer knows when to use it", shows),
      error ? h("div", { class: "field-note warn" }, error) : null,
      h("div", { class: "sadd-actions" }, go,
        h("button", { class: "btn ghost small", type: "button", onclick: () => { adding = false; error = ""; draw(); } }, "Cancel")));
  };
  function draw() {
    const kids = [];
    for (const g of S.screenGroups || []) {
      const rows = (S.screens || []).filter((e) => e.group === g.id);
      if (!rows.length && g.id !== "mine") continue;
      kids.push(h("section", { class: "sgroup" },
        h("h3", { class: "sgroup-title" }, g.title, rows.length ? h("span", { class: "muted" }, String(rows.length)) : null),
        g.id === "mine" && !rows.length && !adding ? h("p", { class: "sgroup-note" },
          "Nothing here yet. Add a screenshot or a screen recording from your phone and it can go in any video.") : null,
        h("div", { class: "sgrid" }, rows.map(tile),
          g.id === "mine" && !adding ? h("button", { class: "stile add", type: "button", onclick: () => { adding = true; error = ""; draw(); } },
            h("span", { class: "stile-pic" }, icon("plus", 24)),
            h("span", { class: "stile-title" }, "Add your own"),
            h("span", { class: "stile-shows" }, "A screenshot or a screen recording from your phone")) : null),
        g.id === "mine" && adding ? addForm() : null));
    }
    box.replaceChildren(...kids);
  }
  draw();
  return box;
}

// Choose app screens in a dialog. max 1: one screen (always returns one). max > 1: up to max,
// and none is a fine answer ("let the writer choose"). Resolves to the paths, or null on cancel.
function screenPicker({ title, text, max = 1, selected = [], allowEmpty = false }) {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    let picks = selected.filter((p) => screenFor(p));
    const close = (v) => { root.replaceChildren(); document.removeEventListener("keydown", key); resolve(v); };
    const key = (e) => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", key);
    const count = h("span", { class: "spick-count" });
    const okBtn = h("button", { class: "btn primary", type: "button", onclick: () => close(picks) });
    const clearBtn = allowEmpty ? h("button", { class: "btn ghost", type: "button", onclick: () => { picks = []; sync(); gridBox.replaceChildren(makeGrid()); } }, "Clear") : null;
    const sync = () => {
      if (clearBtn) clearBtn.classList.toggle("hidden", !picks.length);
      count.textContent = max > 1 ? `${picks.length} of ${max} picked` : picks.length ? screenTitle(picks[0]) : "";
      okBtn.textContent = !picks.length ? "Let the writer choose" : picks.length === 1 ? "Use this screen" : `Use these ${picks.length}`;
      okBtn.disabled = !picks.length && !allowEmpty;
    };
    const makeGrid = () => screenGrid({
      isOn: (p) => picks.includes(p),
      orderOf: (p) => (max > 1 ? picks.indexOf(p) + 1 : 0),
      onPick: (e) => {
        if (picks.includes(e.path)) picks = allowEmpty || max > 1 ? picks.filter((p) => p !== e.path) : picks;
        else if (max === 1) picks = [e.path];
        else if (picks.length < max) picks = [...picks, e.path];
        else toast(`This format shows at most ${max}. Unpick one first.`, "bad");
        sync();
      },
      onGone: (p) => { picks = picks.filter((x) => x !== p); sync(); },
    });
    const gridBox = h("div", {}, makeGrid());
    sync();
    root.replaceChildren(h("div", { class: "modal-back", onclick: (e) => e.target === e.currentTarget && close(null) },
      h("div", { class: "modal wide", role: "dialog", "aria-modal": "true", "aria-label": title },
        h("div", { class: "modal-head" }, h("div", {}, h("h2", {}, title), text ? h("p", {}, text) : null),
          h("button", { class: "icon-btn", type: "button", title: "Close", "aria-label": "Close", onclick: () => close(null) }, icon("x", 16))),
        h("div", { class: "modal-scroll" }, gridBox),
        h("div", { class: "actions" }, count, h("span", { style: "flex:1" }), clearBtn,
          h("button", { class: "btn ghost", type: "button", onclick: () => close(null) }, "Cancel"), okBtn))));
  });
}

// The create screen's "App screens" card: pin the screenshots this video shows, or leave it open.
function screensSection(f, st) {
  const max = (f.limits || {}).app_screens || 0;
  if (!max || !(S.screens || []).length) return null;
  const body = h("div", { class: "spicked" });
  const note = h("span", { class: "count-note" });
  const choose = async () => {
    const r = await screenPicker({ title: max === 1 ? "Which app screen should this video show?" : `Which app screens should this video show? Up to ${max}.`,
      text: "These are the real app. The video shows them on a phone, in the hero's hand. A play mark means the screen moves; hover to watch.", max, selected: st.screens, allowEmpty: true });
    if (r) { st.screens = r; draw(); }
  };
  function draw() {
    st.screens = st.screens.filter((p) => screenFor(p));
    note.textContent = st.screens.length ? `${st.screens.length} of ${max} picked` : "The writer chooses";
    const kids = st.screens.map((p) => {
      const e = screenFor(p);
      return h("div", { class: "spick" }, h("img", { src: e.url, alt: "" }),
        h("span", { class: "spick-text" }, h("b", {}, e.title), h("span", {}, e.shows)),
        h("button", { class: "icon-btn", type: "button", title: "Do not pin this screen", "aria-label": `Unpin ${e.title}`,
          onclick: () => { st.screens = st.screens.filter((x) => x !== p); draw(); } }, icon("x", 14)));
    });
    if (!st.screens.length) {
      const some = S.screens.slice(0, 6);
      kids.push(h("button", { class: "spreview", type: "button", onclick: choose, "aria-label": "Choose app screens" },
        some.map((e) => h("img", { src: e.url, alt: "", loading: "lazy" })),
        S.screens.length > some.length ? h("span", { class: "spreview-more" }, `+${S.screens.length - some.length}`) : null));
    }
    kids.push(h("button", { class: "btn small", type: "button", onclick: choose }, icon("phone", 14),
      st.screens.length ? "Change" : max === 1 ? "Choose the screen" : "Choose screens"));
    body.replaceChildren(...kids);
  }
  draw();
  return h("section", { class: "card-sec", id: "sec-screens" },
    h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "App screens"), note), body,
    h("div", { class: "field-note" }, max === 1
      ? "The demo beat shows one real screenshot on a phone. Pick it here, or leave it to the script writer. You can swap it after, for free."
      : `The demo beat shows real screenshots on a phone. Pick up to ${max} here, or leave it to the script writer. You can swap them after, for free.`));
}

// The library on its own page: everything a video can show, and where you add your own.
function renderScreens() {
  const draw = () => $("#main").replaceChildren(h("div", { class: "view studio" },
    h("div", { class: "studio-head" },
      h("div", {}, h("h1", {}, "App screens"),
        h("p", { class: "lede" }, "Real screens of the app. A video shows them on a phone in its demo beat. The ones with a play mark are recordings: the screen moves. Pick which ones when you make a video, or swap one later in the script editor.")),
      h("span", { class: "muted", style: "font-size:12px;white-space:nowrap" }, plural((S.screens || []).length, "screen"))),
    screenGrid()));
  draw();
  loadScreens().then(() => { if (location.hash === "#/screens") draw(); });
}


// The ElevenLabs voice list (free, cached on the server). Loaded once; "refresh" asks again.
async function loadVoices(refresh) {
  try {
    const r = await api("GET", `/api/voices${refresh ? "?refresh=true" : ""}`);
    S.voices = r.voices || []; S.voicesError = r.error;
  } catch (e) { S.voices = []; S.voicesError = e.message; }
  return S.voices;
}
function voiceLabel(v) {
  return [v.name, [v.gender, (v.age || "").replace("_", " "), v.accent].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
}
function playPreview(voiceId, btn) {
  const v = (S.voices || []).find((x) => x.voice_id === voiceId);
  if (S.preview) { S.preview.pause(); S.preview = null; }
  if (!v || !v.preview_url) { toast("No preview for this voice.", "bad"); return; }
  const a = new Audio(v.preview_url); S.preview = a;
  btn.textContent = "■"; a.onended = a.onpause = () => { btn.textContent = "▶"; };
  a.play().catch(() => { btn.textContent = "▶"; toast("Could not play the preview.", "bad"); });
}
function voiceSelect(current, onChange, { emptyLabel, label }) {
  const known = (S.voices || []).some((v) => v.voice_id === current);
  return h("select", { "aria-label": label, onchange: (e) => onChange(e.target.value) },
    emptyLabel ? h("option", { value: "", selected: !current }, emptyLabel) : null,
    current && !known ? h("option", { value: current, selected: true }, `${current.slice(0, 10)}… (not in your list)`) : null,
    (S.voices || []).map((v) => h("option", { value: v.voice_id, selected: v.voice_id === current }, voiceLabel(v))));
}

async function loadChars() {
  try { S.chars = await api("GET", "/api/characters"); S.charsLoaded = true; } catch { S.chars = S.chars || []; }
  const c = $("#char-count"); if (c) c.textContent = S.chars.length ? S.chars.length : "";
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
    if (!keepDraft || S.storyFor !== runId || !storyChanged()) {
      S.storyDraft = run.story ? structuredClone(run.story) : null;
      S.storyFor = runId;
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
  paintProgress();
  if (finished.length || jobs.some((j) => ACTIVE.has(j.status) && !S.runs.some((r) => r.run_id === j.run_id))) refreshRuns();
}

function onJobFinished(job) {
  if (job.run_id) S.stamps[job.run_id] = Date.now();
  toast(`${job.action}${job.params && job.params.step ? ` ${job.params.step}` : ""} ${job.status === "done" ? "finished" : "failed"}${job.error ? `: ${job.error}` : ""}`,
    job.status === "done" ? "ok" : "bad");
  if (job.run_id && job.run_id === S.runId) loadRun(S.runId);
  if (job.action === "draw_character") {
    loadChars().then(() => { if (location.hash.startsWith("#/characters")) route(); });
  }
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
let lastProgressMark = "";
async function refreshOpenRun() {
  if (!S.runId || !S.run || !S.jobs.some((j) => j.run_id === S.runId && j.status === "running")) return;
  // Look again as soon as the job reports another finished piece, else every few seconds.
  const job = S.jobs.find((j) => j.run_id === S.runId && j.status === "running");
  const mark = job && job.progress ? `${job.id}:${job.progress.step}:${job.progress.done}` : "";
  if (mark === lastProgressMark && Date.now() - lastProgressCheck < 3000) return;
  lastProgressMark = mark;
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

// ------------------------------------------------------------ progress bar
const STEP_DOING = { script: "Writing the script", images: "Drawing images", video: "Animating clips",
  voice: "Recording voices", assemble: "Putting the video together", story: "Writing the story",
  scenes: "Coding the scenes", render: "Rendering the video" };

function elapsed(iso) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (!iso || isNaN(s)) return "";
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`
    : `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

// What to show for a run's active job. size: "full" (run page), "line" (job bar), "mini" (sidebar).
function progressKids(job, size) {
  if (!job) return [];
  const bar = (pct, moving) => h("div", { class: `pbar${moving ? " moving" : ""}`, role: "progressbar",
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct) },
    h("div", { class: "pbar-fill", style: `width:${Math.max(pct, moving ? 100 : 2)}%` }));
  if (job.status === "queued") {
    return size === "mini" ? [] : [h("div", { class: "p-line" }, h("span", { class: "p-what" }, "Waiting for the job ahead to finish"))];
  }
  const p = job.progress;
  if (!p) return size === "mini" ? [bar(0, true)] : [h("div", { class: "p-line" }, h("span", { class: "p-what" }, "Starting…")), bar(0, true)];
  const counted = p.total > 0;
  if (size === "mini") return [bar(p.percent, !counted && p.count === 1)];
  const what = STEP_DOING[p.step] || p.step;
  const detail = counted ? (p.unit ? `${p.done} of ${p.total} ${p.unit}` : "") : "";
  const stepOf = p.count > 1 ? `Step ${p.index} of ${p.count}` : "";
  // A one-step job with nothing to count (the script) has no meaningful percentage.
  const pct = p.count === 1 && !counted ? "" : `${p.percent}%`;
  const line = h("div", { class: "p-line" },
    h("span", { class: "p-what" }, what, detail ? h("span", { class: "p-detail" }, ` · ${detail}`) : null),
    h("span", { class: "p-meta" }, [stepOf, pct, job.started_at ? elapsed(job.started_at) : ""].filter(Boolean).join(" · ")));
  return [line, bar(p.percent, !counted)];
}

function activeJobFor(runId) {
  return S.jobs.find((j) => j.run_id === runId && j.status === "running")
    || S.jobs.find((j) => j.run_id === runId && j.status === "queued");
}

// Fill every progress slot on the page from the latest job list (called on each poll, so the
// bars move without re-rendering the page around them).
function paintProgress() {
  document.querySelectorAll("[data-progress-run]").forEach((el) => {
    const kids = progressKids(activeJobFor(el.dataset.progressRun), el.dataset.size || "full");
    el.replaceChildren(...kids);
    el.classList.toggle("empty", !kids.length);
  });
  const slot = $("#drawer-progress");
  if (slot) {
    const running = S.jobs.find((j) => j.status === "running");
    const p = running && running.progress;
    slot.replaceChildren(...(running ? [h("div", { class: `pbar${!p || !p.total ? " moving" : ""}` },
      h("div", { class: "pbar-fill", style: `width:${p && p.total ? Math.max(p.percent, 2) : 100}%` })),
      p && (p.total || p.count > 1) ? h("span", { class: "p-pct" }, `${p.percent}%`) : null].filter(Boolean) : []));
  }
}
function progressSlot(runId, size) {
  const el = h("div", { class: `progress ${size}`, "data-progress-run": runId, "data-size": size });
  const kids = progressKids(activeJobFor(runId), size);
  el.replaceChildren(...kids);
  el.classList.toggle("empty", !kids.length);
  return el;
}

// ---------------------------------------------------------- caption styles
function captionStyles() { return (S.config && S.config.caption_styles) || []; }
function captionTitle(id) { const c = captionStyles().find((x) => x.id === id); return c ? c.title : id; }
function captionPreview(formatName, id) {
  if (id === "off") return h("div", { class: "cap-img off" }, "No captions");
  const img = h("img", { class: "cap-img", loading: "lazy", alt: "", src: `/caption-preview/${encodeURIComponent(formatName)}/${encodeURIComponent(id)}` });
  img.addEventListener("error", () => img.replaceWith(h("div", { class: "cap-img off" }, "Aa")));
  return img;
}
// The picker on the create screen: one tile per style, drawn the way this format will show it.
function captionPicker(formatName, value, onChange) {
  const box = h("div", { class: "cap-grid", role: "radiogroup", "aria-label": "Caption style" });
  const draw = (current) => box.replaceChildren(...captionStyles().map((c) =>
    h("button", { type: "button", class: `cap-tile${c.id === current ? " on" : ""}`, role: "radio", "aria-checked": String(c.id === current),
      title: c.note, onclick: () => { draw(c.id); onChange(c.id); } },
      captionPreview(formatName, c.id), h("span", { class: "cap-name" }, c.title))));
  draw(value);
  return box;
}

function captionsPanel(run, busy) {
  const box = h("section", { class: "captions-panel", "aria-label": "Captions" });
  const draw = () => {
    const current = run.caption_style || "format";
    const sel = h("select", { "aria-label": "Caption style", disabled: busy, onchange: async (e) => {
      try {
        const r = await api("PUT", `/api/runs/${encodeURIComponent(run.run_id)}/captions`, { style: e.target.value });
        run.caption_style = r.caption_style;
        S.captionRedo = r.assembled ? run.run_id : null;
      } catch (err) { toast(err.message, "bad"); }
      draw();
    } }, captionStyles().map((c) => h("option", { value: c.id, selected: c.id === current }, c.title)));
    const redo = S.captionRedo === run.run_id;
    box.replaceChildren(...[
      h("div", { class: "panel-title" }, "Captions"),
      h("div", { class: "cap-row" }, captionPreview(run.format, current), sel),
      redo ? h("div", { class: "notice" }, `The finished video still has the old captions. `,
        h("button", { class: "btn small", disabled: busy, onclick: () => { S.captionRedo = null; runStep(run, "assemble"); } }, "Assemble again"),
        h("div", { class: "field-note" }, "Assembling makes no API calls, so it costs nothing.")) : null,
      !redo ? h("div", { class: "field-note" }, "Change the look any time. Only the assemble step runs again, which is free.") : null,
    ].filter(Boolean));
  };
  draw();
  return box;
}

// --------------------------------------------------------------- sidebar
function runState(r) {
  if (r.job && ACTIVE.has(r.job.status)) return r.job.status;
  if (r.job && r.job.status === "failed") return "failed";
  const last = r.engine === "claude_code" ? "render" : "assemble";
  const first = r.engine === "claude_code" ? "story" : "script";
  if (r.steps[last].status === "done") return "done";
  if (r.steps[first].status === "done" && Object.entries(r.steps).every(([k, v]) => k === first || v.status !== "done" && v.status !== "partial")) return "script";
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
  const cl = $("#chars-link"); if (cl) cl.classList.toggle("active", location.hash.startsWith("#/characters"));
  if (!S.runs.length) { nav.replaceChildren(h("div", { class: "empty-side" }, "No runs yet. Make your first video.")); return; }
  nav.replaceChildren(...S.runs.map((r) => {
    const st = runState(r);
    return h("a", { class: `run-item${r.run_id === S.runId ? " active" : ""}`, href: `#/run/${encodeURIComponent(r.run_id)}`,
      title: `${r.premise}\n${STATE_LABEL[st]}` },
      h("div", { class: "premise" }, h("span", { class: `dot ${st}`, "aria-label": STATE_LABEL[st] }), h("span", {}, r.premise || r.run_id)),
      h("div", { class: "meta" }, h("span", {}, formatName(r.format)), r.engine === "claude_code" ? h("span", { class: "eng" }, "Claude Code") : null,
        h("span", {}, "·"), h("span", {}, st === "done" ? when(r.created_at) : STATE_LABEL[st])),
      progressSlot(r.run_id, "mini"));
  }));
}

// ---------------------------------------------------------- studio views
function formatTitle(f) { return f.title || f.name.replace(/_/g, " "); }
// A format's display name from its id ("pixar_mirror" -> "Pixar Mirror").
function formatName(id) {
  const f = S.formats.find((x) => x.name === id);
  return f && !f.error ? formatTitle(f) : String(id || "").replace(/_/g, " ");
}

// A format with no cover yet gets a quiet stand-in: a dark tint keyed to its name, its initial.
function coverArt(f, big) {
  const hue = [...f.name].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
  return h("div", { class: `cover-art${big ? " big" : ""}`,
    style: `background: radial-gradient(110% 70% at 50% 30%, hsl(${hue} 38% 24%), hsl(${hue} 30% 11%) 72%, #0a0c13)` },
    h("span", { class: "cover-initial" }, formatTitle(f).slice(0, 1)));
}

function coverImg(f) {
  if (!f.cover) return coverArt(f);
  return h("img", { src: f.cover, alt: "", loading: "lazy" });
}

// The gallery is grouped by what kind of video a format makes.
const FAMILIES = [
  ["pixar", "Pixar stories", "3D animated character stories. One cast, five story shapes."],
  ["people", "People talking", "Someone to camera, an interview, a podcast clip."],
  ["looks", "Animated looks", "A short narrated story ad in one visual style."],
  ["other", "Letters and songs", "The words are the picture."],
];
function formatFamily(f) {
  const L = f.limits || {};
  if (f.name.startsWith("pixar_")) return "pixar";
  if (L.talking) return "people";
  if (L.song || L.letter) return "other";
  return "looks";
}
function formatCard(f) {
  const est = estimateNew(f.name, "");
  const len = (f.duration_target || "").replace(/^about\s+/i, "");
  return h("a", { class: `fcard${f.default ? " default" : ""}${f.cover ? "" : " nocover"}`, href: `#/new/${encodeURIComponent(f.name)}`,
    title: f.description },
    h("div", { class: "fcard-img" }, coverImg(f), f.default ? h("span", { class: "fcard-tag" }, "Default") : null),
    h("div", { class: "fcard-body" },
      h("div", { class: "fcard-title" }, formatTitle(f)),
      h("div", { class: "fcard-desc" }, f.description)),
    h("div", { class: "fcard-cost" }, h("span", {}, len), h("span", { class: "fcard-price", title: "A rough cost for one video" }, `about ${usd(est.total)}`)));
}
function studioSections() {
  const q = S.studioQuery.trim().toLowerCase();
  const formats = S.formats.filter((f) => !f.error
    && (!q || `${formatTitle(f)} ${f.description} ${f.name}`.toLowerCase().includes(q)));
  if (!formats.length) {
    return [h("div", { class: "empty" }, `No format matches \u201c${S.studioQuery.trim()}\u201d. Try a look ("comic") or a kind of story ("interview").`)];
  }
  return FAMILIES.map(([key, title, sub]) => {
    const list = formats.filter((f) => formatFamily(f) === key)
      .sort((x, y) => (y.default ? 1 : 0) - (x.default ? 1 : 0) || formatTitle(x).localeCompare(formatTitle(y)));
    if (!list.length) return null;
    return h("section", { class: "fsec", "aria-label": title },
      h("div", { class: "fsec-head" }, h("h2", {}, title), h("span", { class: "fsec-sub" }, sub)),
      h("div", { class: "fgrid" }, list.map(formatCard)));
  });
}
function renderStudio() {
  const broken = S.formats.filter((f) => f.error);
  const total = S.formats.length - broken.length;
  const sections = h("div", { id: "fsections" }, studioSections());
  const search = h("label", { class: "search" }, icon("search"),
    h("input", { type: "search", placeholder: `Search ${total} formats`, value: S.studioQuery, "aria-label": "Search formats",
      oninput: (e) => { S.studioQuery = e.target.value; sections.replaceChildren(...studioSections().filter(Boolean)); } }));
  $("#main").replaceChildren(h("div", { class: "view studio" },
    doctorNotice(),
    h("div", { class: "studio-head" },
      h("div", {}, h("h1", {}, "What are we making?"),
        h("p", { class: "lede" }, "Pick a format: a look and a story shape. You write a sentence or two, VidGen makes the video.")),
      search),
    sections,
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
  const st = { provider: "", dry: false, engine: "ai", cast: [], captions: S.config.caption_style || "format", screens: [] };
  const hasCode = (f.engines || []).includes("claude_code");
  const d = S.config.providers.default;
  const premise = h("textarea", { class: "premise-box", id: "f-premise", rows: "6", maxlength: String(PREMISE_MAX),
    placeholder: f.limits && f.limits.narrator ? "A baker's oven dies the day her cake goes viral…"
      : "A laid-off line cook buys a beat-up food truck and nobody shows up on day one…" });
  const count = h("span", { class: "count-note" });
  const costLine = h("div", { class: "cost-big" }); const costSub = h("div", { class: "cost-sub" });
  const keyWarn = h("div", { class: "field-note warn" });
  const go = h("button", { class: "btn primary go", type: "submit" }, "Generate video");
  const codeWarn = h("div", { class: "field-note warn" });
  const update = () => {
    const words = premise.value.trim() ? premise.value.trim().split(/\s+/).length : 0;
    const left = PREMISE_MAX - premise.value.length;
    count.textContent = !words ? "One or two sentences is plenty"
      : left <= 0 ? `${words} words. That is the limit, nothing more will fit`
      : left < 200 ? `${words} words, room for ${left} more characters` : `${words} words`;
    const kinds = new Set([providerFor("images", st.provider), providerFor("video", st.provider)]);
    const missing = [...kinds].filter((p) => !S.config.keys_present[p === "fal" ? "FAL_KEY" : "SUME_API_KEY"]);
    keyWarn.textContent = missing.length ? `No API key set for ${missing.join(", ")}.` : "";
    provSec.classList.toggle("hidden", st.engine === "claude_code");
    capSec.classList.toggle("hidden", st.engine === "claude_code");
    if (scrSec) scrSec.classList.toggle("hidden", st.engine === "claude_code");
    codeWarn.textContent = st.engine === "claude_code" ? codeEngineProblem() : "";
    if (st.engine === "claude_code") {
      const est = estimateCode(f.name);
      costLine.textContent = st.dry ? "free" : `about ${usd(est.total)}`;
      costSub.textContent = st.dry ? "Claude Code writes the story on your Claude plan. Nothing else runs."
        : "Claude Code writes and codes it on your Claude plan · voice by ElevenLabs · renders on this computer";
      go.textContent = st.dry ? "Write the story" : "Make video";
      return;
    }
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
      L.story_shots ? [h("dt", {}, "Shots"), h("dd", {}, `${L.story_shots[0]}-${L.story_shots[1]}${L.montage ? ` + ${L.montage[0]}-${L.montage[1]} montage` : ""}${L.flashes ? ` + ${L.flashes[0]}-${L.flashes[1]} flashes` : ""}`)] : null,
      L.vo_words ? [h("dt", {}, "Spoken words"), h("dd", {}, `${L.vo_words[0]}-${L.vo_words[1]}${L.narrator ? ", narrated" : ", dialogue only"}`)] : null,
      h("dt", {}, "Clips"), h("dd", {}, L.animate_all ? `${L.flashes ? "every shot but the flashes" : "every shot"} is a clip × ${f.clip_seconds || 4}s` : `up to ${L.max_animated_shots ?? "?"} × ${f.clip_seconds || 4}s`),
      f.locked_cast.length ? [h("dt", {}, "Cast"), h("dd", {}, f.locked_cast.join(", "))] : null,
      L.cta_caption ? [h("dt", {}, "Ends on"), h("dd", {}, L.cta_caption)] : null),
    f.beats.length ? h("ol", { class: "beat-list" }, f.beats.map((b) => h("li", {}, b))) : null,
    (f.references || []).length ? h("div", { class: "refs" },
      h("div", { class: "refs-title" }, "Modelled on"),
      f.references.map((r) => h("a", { class: "ref", href: r.url, target: "_blank", rel: "noopener noreferrer" },
        icon("external", 14), h("span", {}, r.note || r.url)))) : null);
  if ((f.references || []).length) details.open = true;

  const outputBox = h("div");
  const drawOutput = () => outputBox.replaceChildren(chips(
    [[false, "Full video"], [true, st.engine === "claude_code" ? "Story only" : "Script only", st.engine === "claude_code" ? "free" : "a few cents"]],
    st.dry, (v) => { st.dry = v; update(); }, "Output"));
  drawOutput();
  const provSec = h("section", { class: "card-sec" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Provider")),
    chips([["", "Default", `${d.images} / ${d.video}`], ["fal", "fal"], ["sume", "Sume"]], st.provider, (v) => { st.provider = v; update(); }, "Provider"),
    keyWarn);
  const capSec = h("section", { class: "card-sec" },
    h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Captions")),
    captionPicker(f.name, st.captions, (v) => { st.captions = v; }),
    h("div", { class: "field-note" }, "You can change this after the video is made, for free."));
  const scrSec = screensSection(f, st);
  S.onDoctor = update;
  const form = h("form", { class: "create-left", onsubmit: async (e) => {
    e.preventDefault();
    const text = premise.value.trim();
    if (!text) { premise.focus(); toast("Write a premise first.", "bad"); return; }
    if (st.engine === "claude_code" && !st.dry) {
      const est = estimateCode(f.name);
      const ok = await confirmDialog({ title: `Make a ${formatTitle(f)} video with Claude Code?`, rows: est.rows, total: est.total,
        text: "Claude Code writes the story, codes every scene and checks stills; then VidGen adds the voice and renders.",
        ok: "Make video",
        note: "Claude Code runs on your Claude plan and counts toward its usage limits. Rendering happens on this computer and can take several minutes. Choose Story only to read the story first." });
      if (!ok) return;
    } else if (!st.dry) {
      const est = estimateNew(f.name, st.provider);
      const ok = await confirmDialog({ title: `Generate a ${formatTitle(f)} video?`, rows: est.rows, total: est.total,
        text: "Runs script, images, video, voice and assemble.", ok: "Generate",
        note: "An upper bound from the format's limits; the real cost depends on the shot list. Choose Script only to check it first for a few cents." });
      if (!ok) return;
    }
    go.disabled = true;
    const r = await submit(api("POST", "/api/runs", { premise: text, format: f.name, provider: st.engine === "ai" ? (st.provider || null) : null,
      dry_run: st.dry, engine: st.engine, cast: st.cast, captions: st.engine === "ai" ? st.captions : null,
      screens: st.engine === "ai" ? st.screens : [] }),
      st.dry ? (st.engine === "claude_code" ? "story" : "script") : `${formatTitle(f)} video`);
    go.disabled = false;
    if (r) { await refreshRuns(); location.hash = `#/run/${encodeURIComponent(r.run_id)}`; }
  } },
    h("section", { class: "card-sec" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Premise"), count), premise),
    hasCode ? h("section", { class: "card-sec" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Engine")),
      chips([["ai", "Image models", "fal / Sume"], ["claude_code", "Claude Code", "your Claude plan"]], st.engine,
        (v) => { st.engine = v; drawOutput(); update(); }, "Engine"),
      h("div", { class: "field-note" }, "Claude Code codes every scene in this style and renders it here, with no image or video model."),
      codeWarn) : null,
    h("section", { class: "card-sec" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Output")), outputBox),
    scrSec,
    provSec,
    capSec,
    castSection(f, st, update),
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
  // Beside the form: what this format makes. An example when there is one, and always how the
  // story goes and which videos it is modelled on.
  const hasExample = !!(f.example_video || f.cover);
  details.open = true;
  details.querySelector("summary").replaceChildren(h("span", { class: "sec-label" }, "How this video goes"));
  const right = h("div", { class: "create-side" },
    hasExample ? h("section", { class: "create-right" },
      h("div", { class: "sec-label" }, "An example"),
      h("div", { class: "example-wrap" }, frame,
        soundBtn ? h("div", { class: "example-actions" }, soundBtn) : null,
        h("p", { class: "example-note" }, `A finished ${formatTitle(f)}. Yours follows the same shape.`))) : null,
    details,
    hasExample ? null : h("p", { class: "example-note left" },
      "No example video for this format yet. After you make one, \u201cUse as example\u201d on the finished video puts it here."));

  $("#main").replaceChildren(h("div", { class: "view create" },
    h("a", { class: "back-link", href: "#/new" }, icon("chevron-left", 14), "All formats"),
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
  box.replaceChildren(h("details", { class: "setup" },
    h("summary", {}, icon("alert"),
      h("span", { class: "setup-title" }, `Setup: ${plural(fails.length, "thing")} to fix before a video can be made`),
      h("span", { class: "setup-items" }, fails.map((c) => c.item).join(" · ")),
      h("span", { class: "setup-more" }, "Details")),
    h("ul", {}, fails.map((c) => h("li", {}, h("b", {}, c.item), ": ", c.detail))),
    h("p", { class: "field-note" }, "To check again from a terminal: python main.py doctor")));
}
async function loadDoctor() {
  try { S.doctor = await api("GET", "/api/doctor"); } catch (e) { S.doctor = { error: e.message }; }
  fillDoctor($("#doctor-box"));
  if (S.onDoctor) S.onDoctor();
}

// Why the Claude Code engine cannot run on this computer, from the setup check ("" if it can).
const CODE_CHECKS = ["node", "npm", "claude (Claude Code)", "Claude Code login"];
function codeEngineProblem() {
  if (!S.doctor || !S.doctor.checks) return "";
  const bad = S.doctor.checks.filter((c) => CODE_CHECKS.includes(c.item) && c.status !== "PASS");
  return bad.length ? `Not ready on this computer: ${bad.map((c) => `${c.item}: ${c.detail}`).join(" · ")}` : "";
}

function estimateCode(formatName) {
  const f = S.formats.find((x) => x.name === formatName);
  const chars = f && f.limits && f.limits.vo_words ? f.limits.vo_words[1] * 6 : 400;
  const rows = [["Story + scenes (Claude Code)", "your Claude plan"],
    [`up to ~${chars} characters of voice`, voiceCost(chars)], ["Rendering", "on this computer"]];
  return { rows, total: voiceCost(chars) };
}

// ------------------------------------------------------------- cast picker
function charFace(src, name, size = "") {
  return src ? h("img", { class: `face-img ${size}`, src, alt: "" })
    : h("span", { class: `face-img ${size} none` }, (name || "?").slice(0, 1).toUpperCase());
}

function castSection(f, st, onChange) {
  const box = h("section", { class: "card-sec cast-sec" });
  const swaps = {};        // format character id -> library id
  const adds = [];         // [{character, role}]
  const sync = () => {
    st.cast = [...Object.entries(swaps).filter(([, v]) => v).map(([rep, c]) => ({ character: c, replaces: rep, role: "" })),
      ...adds.filter((a) => a.character).map((a) => ({ character: a.character, replaces: null, role: a.role }))];
    onChange();
  };
  const used = () => new Set([...Object.values(swaps), ...adds.map((a) => a.character)].filter(Boolean));
  const libOptions = (current) => S.chars.map((c) => h("option", { value: c.id, selected: c.id === current,
    disabled: c.id !== current && used().has(c.id) }, c.name));
  const draw = () => {
    const chars = f.characters || [];
    const rows = chars.map((c) => {
      const lib = swaps[c.id] && S.chars.find((x) => x.id === swaps[c.id]);
      return h("div", { class: `cast-row${lib ? " swapped" : ""}`, title: lib ? lib.description || "" : c.description || "" },
        charFace(lib ? lib.image : c.image, lib ? lib.name : c.id),
        h("div", { class: "cast-who" }, h("b", {}, lib ? lib.name : c.id), h("span", {}, lib ? `as ${c.role || c.id}` : c.role),
          !lib && c.redraw ? h("span", { class: "cast-new" }, "New look. Drawn on your next video.") : null),
        S.chars.length ? h("select", { "aria-label": `Who plays ${c.id}`, onchange: (e) => { swaps[c.id] = e.target.value; sync(); draw(); } },
          h("option", { value: "", selected: !swaps[c.id] }, `${c.id} (format)`), libOptions(swaps[c.id])) : null);
    });
    const added = adds.map((a, i) => {
      const lib = S.chars.find((x) => x.id === a.character);
      return h("div", { class: "cast-row added" },
        charFace(lib && lib.image, lib && lib.name),
        h("div", { class: "cast-who" },
          h("select", { "aria-label": "Character to add", onchange: (e) => { a.character = e.target.value; sync(); draw(); } }, libOptions(a.character)),
          h("input", { type: "text", value: a.role, placeholder: lib && lib.role ? lib.role : "role in the story (optional)", "aria-label": "Role",
            oninput: (e) => { a.role = e.target.value; sync(); } })),
        h("button", { type: "button", class: "icon-btn", title: "Remove", "aria-label": "Remove", onclick: () => { adds.splice(i, 1); sync(); draw(); } }, "✕"));
    });
    const free = S.chars.filter((c) => !used().has(c.id));
    box.replaceChildren(...[
      h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Cast"),
        h("a", { class: "muted small-link", href: "#/characters" }, S.chars.length ? "Your characters ›" : "")),
      rows.length ? h("div", { class: "cast-list" }, rows) : h("div", { class: "field-note" }, "This format invents its cast for each story."),
      added.length ? h("div", { class: "cast-list" }, added) : null,
      S.chars.length
        ? (free.length ? h("button", { type: "button", class: "btn small", onclick: () => { adds.push({ character: free[0].id, role: "" }); sync(); draw(); } },
            "+ Add one of your characters") : null)
        : h("div", { class: "field-note" }, "Put yourself or your own characters in the story: ",
            h("a", { href: "#/characters/new", class: "link" }, "make a character"), "."),
    ].filter(Boolean));
  };
  draw();
  return box;
}

// -------------------------------------------------------------- run view
const STEP_NAME = { script: "Script", images: "Images", video: "Clips", voice: "Voices", assemble: "Final cut" };
const STEP_GO = { script: "Write the script", images: "Make the images", video: "Make the clips", voice: "Record the voices",
  assemble: "Assemble the video" };
function renderRun() {
  if (S.run.engine === "claude_code") { renderCodeRun(); return; }
  const run = S.run;
  const busy = runBusy(run.run_id);
  const active = S.jobs.find((j) => j.run_id === run.run_id && ACTIVE.has(j.status));
  const d = S.config.providers.default;
  const provSel = h("select", { "aria-label": "Provider for actions", disabled: busy, onchange: (e) => { S.provider = e.target.value; } },
    h("option", { value: "", selected: !S.provider }, `default (${d.images}/${d.video})`),
    h("option", { value: "fal", selected: S.provider === "fal" }, "fal"),
    h("option", { value: "sume", selected: S.provider === "sume" }, "Sume"));
  const lastProv = lastProvider(run.run_id);

  // The next step that still has work to do gets the one bright button on the page.
  const next = STEPS.find((s) => !["done", "n/a"].includes(run.steps[s].status));
  const stepBtns = [];
  STEPS.forEach((step, i) => {
    const st = run.steps[step];
    if (i) stepBtns.push(h("span", { class: `step-arrow${st.status === "done" ? " done" : ""}` }));
    stepBtns.push(h("button", { class: `step-btn ${st.status === "n/a" ? "na" : st.status}${step === next ? " next" : ""}`,
      disabled: busy || (step !== "script" && !run.script),
      title: `${STEP_GO[step]}${st.status === "done" ? " again" : ""}`, onclick: () => runStep(run, step) },
      h("span", { class: `dot ${st.status}` }),
      h("span", { class: "step-num" }, st.status === "done" ? icon("check", 12) : String(i + 1)),
      h("span", { class: "step-name" }, STEP_NAME[step]),
      st.total > 1 ? h("span", { class: "count" }, `${st.done}/${st.total}`) : null));
  });
  const finalSrc = run.final_video ? bust(run.final_video, run.run_id) : null;
  const cta = next
    ? h("button", { class: "btn primary cta", disabled: busy || (next !== "script" && !run.script), onclick: () => runStep(run, next) },
      h("span", {}, STEP_GO[next]), icon("arrow-right"))
    : finalSrc ? h("a", { class: "btn primary cta", href: finalSrc, download: `${run.run_id}.mp4` }, icon("download"), h("span", {}, "Download video")) : null;
  const tab = S.runTab[run.run_id] || (run.script && !run.steps.images.done ? "script" : "shots");
  const unsaved = draftChanged().size;
  const tabBtn = (id, label, extra) => h("button", { class: `tab${tab === id ? " on" : ""}`, role: "tab", "aria-selected": tab === id ? "true" : "false",
    onclick: () => { S.runTab[run.run_id] = id; renderMain(); } }, icon(id === "shots" ? "grid" : "text", 15), h("span", {}, label), extra);

  const head = h("header", { class: "run-head" },
    h("div", { class: "run-top" },
      h("h1", { class: "run-title", title: run.premise || "" }, run.premise || run.run_id),
      cta),
    h("div", { class: "run-sub" },
      h("span", { class: "pill" }, formatName(run.format)),
      h("span", { class: "run-prov" }, "Made with ", provSel),
      lastProv ? h("span", { class: "dim" }, `last run with ${lastProv}`) : null,
      h("span", { class: "cost", title: run.cost.rows.map((r) => `${r.item}: ${usd(r.usd)}`).join("\n") }, `est. ${usd(run.cost.total)}`),
      h("span", { class: "dim" }, when(run.created_at)),
      busy ? h("span", { class: "busy-note" }, h("span", { class: `dot ${active.status}` }),
        `${active.action}${active.params.step ? ` ${active.params.step}` : ""} ${active.status}…`) : null),
    progressSlot(run.run_id, "full"),
    h("div", { class: "steps" }, stepBtns,
      h("span", { style: "flex:1" }),
      h("button", { class: "btn small ghost", disabled: busy || !run.script, onclick: () => recast(run),
        title: "Apply the format's locked character descriptions to this run" }, "Recast")),
    run.script ? h("div", { class: "tabs", role: "tablist", "aria-label": "What to look at" },
      tabBtn("shots", "Shots", h("span", { class: "tab-count" }, String(run.shots.length))),
      tabBtn("script", "Script and editing", unsaved ? h("span", { class: "tab-dot", title: "Unsaved changes" }) : null)) : null);

  const mainCol = tab === "script" && run.script
    ? h("section", { class: "shots-col script-col", "aria-label": "Script" }, scriptPanel(run, busy))
    : shotsColumn(run, busy);
  const body = h("div", { class: "run-body" }, mainCol, sideColumn(run, busy));
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
  const drawable = drawsImage(s);
  const spoken = (s.kind === "shot" || s.kind === "letter") && (shot.vo_line || "").trim();
  const selected = S.selected.has(s.n);
  const thumb = h("div", { class: "thumb" });
  if (s.kind === "card") {
    thumb.append(h("div", { class: "card-text" }, shot.card));
  } else if (s.kind === "app_screen") {
    const scr = screenFor(shot.app_screen);
    if (scr && scr.url) {
      thumb.append(h("img", { class: "app-pic", src: scr.url, alt: `App screen: ${scr.title}`, loading: "lazy" }));
      if (scr.clip_url && !shot.app_still) hoverPlay(thumb, scr.clip_url);
    }
    else thumb.append(h("div", { class: "placeholder" }, "App screen", h("br"), (shot.app_screen || "").split("/").pop()));
  } else if (s.image) {
    thumb.append(h("img", { src: bust(s.image, run.run_id), alt: `Shot ${s.n}`, loading: "lazy" }));
    if (!spoken && shot.caption) thumb.append(h("div", { class: "cap" }, shot.caption));
  } else if (s.kind === "letter" && !drawable) {
    thumb.append(h("div", { class: "placeholder low" }, "Same background", h("br"), "as the shot before"));
  } else {
    thumb.append(h("div", { class: "placeholder" }, "No image yet"));
  }
  if (shot.letter) thumb.append(h("div", { class: "letter-peek" }, shot.letter));
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
    shot.animate ? h("span", { class: "badge anim", title: s.clip ? "Animated clip (hover to play)" : "Animated: no clip yet" }, s.clip ? "▶ clip" : "▶ —") : null,
    shot.label ? h("span", { class: "badge kind", title: "On-screen label for this shot" }, shot.label) : null,
    shot.stat ? h("span", { class: "badge stat", title: "Progress overlay: the rank and the number drawn over this shot" }, `${shot.stat.rank} · ${Number(shot.stat.value).toLocaleString("en-US")} ${shot.stat.unit}`) : null,
    shot.same_scene ? h("span", { class: "badge scene", title: "Same scene as the shot before: drawn with that scene's first shot as a reference, so the place and clothes match" }, "↳ scene") : null,
    shot.talk ? h("span", { class: "badge anim", title: s.clip ? "Lip-synced talking clip (hover to play)" : "Talking shot: no clip yet (video step)" }, s.clip ? "talk" : "talk —") : null));
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
      "aria-label": `Use shot ${s.n} as the format cover`, onclick: (e) => { e.stopPropagation(); setFormatMedia(run, "cover", s.n); } }, icon("star", 12)));
  }
  if (s.audio && !run.song) {
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
      : h("div", { class: "line silent" }, s.kind === "card" ? "time card" : s.kind === "app_screen" ? `App screen: ${screenTitle(shot.app_screen)}${(screenFor(shot.app_screen) || {}).clip_url && !shot.app_still ? " (recording)" : ""}` :
        shot.caption ? `caption: ${shot.caption}` : "silent"));
  const actions = h("div", { class: "shot-actions" },
    h("button", { disabled: busy || !drawable, title: shot.talk ? "New keyframe and talking clip" : shot.animate ? "New keyframe and clip" : "New keyframe", onclick: () => reroll(run, s) }, "Reroll"),
    h("button", { disabled: busy || !drawable, title: "Redo the keyframe only", onclick: () => runStep(run, "images", [s.n]) }, "Image"),
    h("button", { disabled: busy || !spoken, title: run.song ? "Make the whole song again" : shot.talk ? "Redo the voice line (then redo its talking clip)" : "Redo the voice line",
      onclick: () => runStep(run, "voice", run.song ? null : [s.n]) }, run.song ? "Song" : "Voice"));
  return h("article", { class: `shot${selected ? " selected" : ""}` }, thumb, info, actions);
}

function sideColumn(run, busy) {
  const col = h("aside", { class: "side-col" });
  const final = h("section", { class: "side-card", "aria-label": "Final video" }, h("div", { class: "panel-title" }, "Final video"));
  if (run.final_video) {
    const src = bust(run.final_video, run.run_id);
    final.append(h("video", { class: "player", controls: true, playsinline: true, preload: "metadata", src }),
      h("div", { class: "final-actions" },
        h("a", { class: "btn small", href: src, download: `${run.run_id}.mp4` }, icon("download", 14), "Download"),
        h("a", { class: "btn small ghost", href: src, target: "_blank", rel: "noopener" }, "Open"),
        h("button", { class: "btn small ghost", onclick: () => setFormatMedia(run, "example"),
          title: "Show this video on the format's page as its example" }, "Use as example")));
  } else {
    final.append(h("div", { class: "player-empty" }, run.script ? "Not assembled yet. It appears here once the images, clips and voices are in." : "No video yet."));
  }
  col.append(final);
  if (run.script && captionStyles().length) col.append(captionsPanel(run, busy));
  if (run.voices && run.voices.length) col.append(voicesPanel(run, busy));
  if (run.song) {
    col.append(h("section", { class: "side-card", "aria-label": "Song" }, h("div", { class: "panel-title" }, "Song"),
      h("div", { class: "song-style" }, run.song.style),
      run.song.audio ? h("audio", { class: "voice-player", controls: true, preload: "none", src: bust(run.song.audio, run.run_id) })
        : h("div", { class: "field-note" }, "Not made yet: run the voice step.")));
  }
  if (run.cost.rows.length) {
    col.append(h("section", { class: "side-card", "aria-label": "Cost" }, h("div", { class: "panel-title" }, "Cost so far"),
      h("div", { class: "cost-rows" },
        run.cost.rows.map((r) => h("div", {}, h("span", {}, r.item), h("span", {}, usd(r.usd)))),
        h("div", { class: "total" }, h("span", {}, "Estimated total"), h("span", {}, usd(run.cost.total))))));
  }
  return col;
}

// ------------------------------------------------------------ voices panel
const VOICE_SOURCE = { auto: "cast for this video", manual: "your pick", config: "from your config", default: "default voice" };
function voicesPanel(run, busy) {
  const box = h("section", { class: "voices-panel", "aria-label": "Voices" });
  const draw = () => {
    const rows = run.voices.map((v) => {
      const spokenShots = run.shots.filter((s) => v.shots.includes(s.n));
      const play = h("button", { class: "icon-btn", type: "button", title: "Hear this voice", "aria-label": `Hear ${v.speaker}'s voice`,
        onclick: (e) => playPreview(v.voice_id, e.currentTarget) }, "▶");
      const pick = async (voiceId) => {
        try {
          const r = await api("PUT", `/api/runs/${encodeURIComponent(run.run_id)}/voices`, { speaker: v.speaker, voice_id: voiceId || null });
          run.voices = r.voices;
          const lines = spokenShots.filter((s) => s.audio).map((s) => s.n);
          S.voiceRedo = lines.length ? { run: run.run_id, speaker: v.speaker, shots: lines } : null;
          draw();
        } catch (e) { toast(e.message, "bad"); draw(); }
      };
      return h("div", { class: "voice-row" },
        h("div", { class: "voice-who" }, h("b", {}, v.speaker),
          h("span", { class: `voice-src ${v.source}` }, VOICE_SOURCE[v.source] || v.source,
            v.gender || v.age ? ` · ${[v.gender, (v.age || "").replace("_", " ")].filter(Boolean).join(", ")}` : "")),
        S.voices && S.voices.length
          ? voiceSelect(v.voice_id, pick, { label: `Voice for ${v.speaker}`, emptyLabel: v.source === "auto" || v.source === "manual" ? "Back to the default" : null })
          : h("span", { class: "dim voice-id" }, v.name || v.voice_id),
        play);
    });
    const redo = S.voiceRedo && S.voiceRedo.run === run.run_id ? S.voiceRedo : null;
    box.replaceChildren(...[
      h("div", { class: "panel-title" }, h("span", {}, "Voices"),
        h("button", { class: "btn small ghost", type: "button", title: "Read the voice list from ElevenLabs again",
          onclick: async () => { await loadVoices(true); draw(); toast(S.voicesError || `${S.voices.length} voices`, S.voicesError ? "bad" : "ok"); } }, "Refresh")),
      S.voicesError ? h("div", { class: "field-note warn" }, S.voicesError) : null,
      h("div", { class: "voice-list" }, rows),
      redo ? h("div", { class: "notice" }, `${redo.speaker} already has ${plural(redo.shots.length, "spoken line")} in the old voice. `,
        h("button", { class: "btn small", disabled: busy, onclick: () => { const r = redo; S.voiceRedo = null; runStep(run, "voice", r.shots); } }, "Redo them")) : null,
      h("div", { class: "field-note" }, "People without a voice of their own get one from your ElevenLabs voices, matched by gender and age. Change any of them here before the voice step."),
    ].filter(Boolean));
  };
  draw();
  if (S.voices === null) loadVoices().then(draw);
  return box;
}

// ----------------------------------------------------------- script panel
function draftChanged() {
  const out = new Set();
  if (!S.run || !S.run.script || !S.draft) return out;
  S.draft.shots.forEach((s, i) => {
    const o = S.run.script.shots[i] || {};
    for (const k of ["vo_line", "speaker", "caption", "card", "letter", "motion_prompt", "image_prompt", "same_scene", "sfx", "label", "app_screen", "app_still"]) if ((s[k] ?? "") !== (o[k] ?? "")) out.add(s.n);
    if (JSON.stringify(s.stat ?? null) !== JSON.stringify(o.stat ?? null)) out.add(s.n);
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
  // What the clip does and what the picture shows, tucked under each drawn shot.
  const lookEditor = (s, i, row) => {
    const o = run.script.shots[i] || {};
    const touched = (s.motion_prompt ?? "") !== (o.motion_prompt ?? "") || (s.image_prompt ?? "") !== (o.image_prompt ?? "")
      || (s.same_scene ?? "") !== (o.same_scene ?? "") || (s.sfx ?? "") !== (o.sfx ?? "")
      || JSON.stringify(s.stat ?? null) !== JSON.stringify(o.stat ?? null);
    // The rank and number drawn over a progress shot.
    const setStat = (key, value) => { S.draft.shots[i].stat = { ...S.draft.shots[i].stat, [key]: value }; update(i, "motion_prompt", S.draft.shots[i].motion_prompt, row); };
    const statEdit = s.stat && run.stats ? h("div", { class: "look-stat" },
      h("label", { class: "look-label" }, "Rank shown",
        h("input", { type: "text", value: s.stat.rank || "", "aria-label": `Shot ${s.n} rank`, placeholder: "GOLD II", title: `One of ${run.stats.ranks.join(", ")}, optionally with I, II or III`,
          oninput: (e) => setStat("rank", e.target.value.toUpperCase()) })),
      h("label", { class: "look-label" }, "Number",
        h("input", { type: "number", min: "0", step: "1", value: String(s.stat.value ?? 0), "aria-label": `Shot ${s.n} number`,
          oninput: (e) => setStat("value", Math.max(0, Math.round(Number(e.target.value) || 0))) })),
      h("label", { class: "look-label" }, "Counts",
        h("select", { "aria-label": `Shot ${s.n} unit`, onchange: (e) => setStat("unit", e.target.value) },
          run.stats.units.map((u) => h("option", { value: u, selected: s.stat.unit === u }, u))))) : null;
    // Offered on shots that have a drawn shot before them to continue (not the first, not a montage shot).
    const prev = S.draft.shots.slice(0, i).reverse().find((x) => !x.app_screen);
    const canContinue = !s.montage && prev && !prev.card && !prev.montage && (prev.image_prompt || "").trim();
    const sceneBox = canContinue ? h("label", { class: "look-check" },
      h("input", { type: "checkbox", checked: s.same_scene === true, "aria-label": `Shot ${s.n} continues the previous scene`,
        onchange: (e) => { if (e.target.checked) update(i, "same_scene", true, row); else { delete S.draft.shots[i].same_scene; update(i, "motion_prompt", S.draft.shots[i].motion_prompt, row); } } }),
      h("span", {}, "Same scene as the shot before: keep its place and clothes")) : null;
    // The sound on the shot's first frame (formats with sound effects only).
    const SOUNDS = [["", "Automatic"], ["none", "None"], ["whoosh", "Whoosh"], ["swish", "Swish (short whoosh)"],
      ["impact", "Impact (deep hit)"], ["pop", "Pop"], ["riser", "Riser (builds up to this shot)"]];
    const soundPick = run.sfx ? h("label", { class: "look-label look-sound" }, "Sound when this shot starts",
      h("select", { "aria-label": `Shot ${s.n} sound`,
        onchange: (e) => { if (e.target.value) update(i, "sfx", e.target.value, row); else { delete S.draft.shots[i].sfx; update(i, "motion_prompt", S.draft.shots[i].motion_prompt, row); } } },
        SOUNDS.map(([v, t]) => h("option", { value: v, selected: (s.sfx || "") === v }, t)))) : null;
    const box = h("details", { class: "look", open: touched || S.lookOpen.has(s.n) },
      h("summary", {}, run.sfx ? "Picture, motion and sound" : "Picture and motion"),
      statEdit,
      sceneBox,
      h("label", { class: "look-label" }, "Motion: what moves in the clip, and the camera",
        h("textarea", { rows: "3", "aria-label": `Shot ${s.n} motion`, placeholder: "the car drives forward and leaves the frame, camera holds on Marcus",
          oninput: (e) => update(i, "motion_prompt", e.target.value, row) }, s.motion_prompt || "")),
      h("label", { class: "look-label" }, "Picture: what the image shows",
        h("textarea", { rows: "5", "aria-label": `Shot ${s.n} picture`,
          oninput: (e) => update(i, "image_prompt", e.target.value, row) }, s.image_prompt || "")),
      soundPick);
    box.addEventListener("toggle", () => { if (box.open) S.lookOpen.add(s.n); else S.lookOpen.delete(s.n); });
    return box;
  };
  const rows = S.draft.shots.map((s, i) => {
    const row = h("div", { class: `srow${changed.has(s.n) ? " dirty" : ""}`, id: `srow-${s.n}` });
    const fields = h("div", { class: "fields" });
    if (s.card) {
      fields.append(h("span", { class: "kind" }, "time card"),
        h("input", { type: "text", value: s.card, "aria-label": `Shot ${s.n} card text`, oninput: (e) => update(i, "card", e.target.value, row) }));
    } else if (s.app_screen) {
      const scr = screenFor(s.app_screen);
      fields.append(h("span", { class: "kind" }, "app screen"),
        h("div", { class: "screen-row" },
          h("span", { class: "screen-text" }, h("b", {}, screenTitle(s.app_screen)), scr && scr.shows ? h("span", { class: "ro" }, scr.shows) : null),
          h("button", { class: "btn small", type: "button", disabled: busy, onclick: async () => {
            const r = await screenPicker({ title: `Shot ${s.n}: which app screen?`, text: "Swapping the screen is free. Assemble again to see it in the video.",
              max: 1, selected: [s.app_screen] });
            if (r && r[0] && r[0] !== s.app_screen) { S.draft.shots[i].app_screen = r[0]; delete S.draft.shots[i].app_still; renderMain(); }
          } }, icon("phone", 14), "Change screen")));
      if (scr && scr.clip_url) {
        fields.append(h("label", { class: "look-check" },
          h("input", { type: "checkbox", checked: s.app_still !== true, "aria-label": `Shot ${s.n} plays the recording`,
            onchange: (e) => { if (e.target.checked) delete S.draft.shots[i].app_still; else S.draft.shots[i].app_still = true; renderMain(); } }),
          h("span", {}, `Play the recording (${Math.round(scr.seconds)} seconds). Untick to show it as a still picture.`)));
      }
      // A line said over the phone (formats that allow it): the speaker and the words can be changed.
      if (((run.script.shots[i] || {}).vo_line || "").trim()) {
        fields.append(h("div", { class: "pair" },
          h("select", { "aria-label": `Shot ${s.n} speaker`, onchange: (e) => update(i, "speaker", e.target.value, row) },
            speakers.map((id) => h("option", { value: id, selected: s.speaker === id }, id)))),
          h("textarea", { rows: "2", "aria-label": `Shot ${s.n} dialogue`, oninput: (e) => update(i, "vo_line", e.target.value, row) }, s.vo_line || ""));
      }
    } else if (s.montage || s.flash) {
      fields.append(h("span", { class: "kind" }, s.flash ? "flash" : "montage"), h("span", { class: "ro" }, s.flash ? "a third of a second, silent" : "silent, no caption"));
      if ((s.image_prompt || "").trim()) fields.append(lookEditor(s, i, row));
    } else {
      const sp = h("select", { "aria-label": `Shot ${s.n} speaker`, onchange: (e) => update(i, "speaker", e.target.value, row) },
        h("option", { value: "", selected: !s.speaker }, "— silent —"),
        speakers.map((id) => h("option", { value: id, selected: s.speaker === id }, id)));
      fields.append(...[
        h("div", { class: "pair" }, sp,
          h("input", { type: "text", value: s.caption || "", placeholder: "caption", "aria-label": `Shot ${s.n} caption`,
            oninput: (e) => update(i, "caption", e.target.value, row) })),
        s.letter !== undefined ? h("textarea", { rows: "2", class: "letter-field", placeholder: "the letter's line", "aria-label": `Shot ${s.n} letter`,
          oninput: (e) => update(i, "letter", e.target.value, row) }, s.letter || "") : null,
        h("textarea", { rows: "2", placeholder: run.song ? "lyric line" : "no dialogue", "aria-label": `Shot ${s.n} ${run.song ? "lyric" : "dialogue"}`,
          oninput: (e) => update(i, "vo_line", e.target.value, row) }, s.vo_line || "")].filter(Boolean));
      if ((s.image_prompt || "").trim()) fields.append(lookEditor(s, i, row));
    }
    const meta = run.shots.find((x) => x.n === s.n);
    const shown = s.app_screen ? screenFor(s.app_screen) : null;
    const pic = shown && shown.url ? h("img", { class: "srow-thumb", src: shown.url, alt: "", loading: "lazy" })
      : meta && meta.image
      ? h("img", { class: "srow-thumb", src: bust(meta.image, run.run_id), alt: "", loading: "lazy" })
      : h("div", { class: "srow-thumb none" }, s.card ? "card" : s.app_screen ? "app" : "no picture");
    row.append(h("div", { class: "srow-side" }, h("span", { class: "num" }, `#${s.n}`), pic), fields);
    return row;
  });
  const saveBtn = h("button", { class: "btn primary small", disabled: busy || !changed.size, onclick: () => saveScript(run) }, "Save script");
  const discard = h("button", { class: "btn ghost small", disabled: !changed.size,
    onclick: () => { S.draft = structuredClone(run.script); S.saveErrors = null; renderMain(); } }, "Discard");
  const wc = h("span", { class: "word-count" }, `${words} spoken words`);
  const topSave = h("button", { class: "btn primary small", disabled: busy || !changed.size, onclick: () => saveScript(run) }, "Save");
  const panel = h("section", { "aria-label": "Script" },
    h("div", { class: "panel-title" }, h("span", {}, "Script"), topSave),
    h("p", { class: "script-help" }, `Change any line, speaker or caption, then save. After saving, VidGen offers to redo just the parts that changed. To change what a shot shows or how it moves, open \u201c${run.sfx ? "Picture, motion and sound" : "Picture and motion"}\u201d under it.`));
  if (S.afterSave && S.afterSave.run === run.run_id && (S.afterSave.sound || []).length) {
    const ns = S.afterSave.sound;
    panel.append(h("div", { class: "notice" }, `Saved. The sound changed on ${ns.length === 1 ? "shot" : "shots"} ${ns.join(", ")}. `,
      h("button", { class: "btn small", disabled: busy, onclick: () => { S.afterSave.sound = []; runStep(run, "assemble"); } }, "Assemble again to hear it")));
  }
  if (S.afterSave && S.afterSave.run === run.run_id && (S.afterSave.screen || []).length) {
    const ns = S.afterSave.screen;
    panel.append(h("div", { class: "notice" }, `Saved. The app screen changed on ${ns.length === 1 ? "shot" : "shots"} ${ns.join(", ")}. `,
      h("button", { class: "btn small", disabled: busy, onclick: () => { S.afterSave.screen = []; runStep(run, "assemble"); } }, "Assemble again to see it")));
  }
  if (S.afterSave && S.afterSave.run === run.run_id && (S.afterSave.overlay || []).length) {
    const ns = S.afterSave.overlay;
    panel.append(h("div", { class: "notice" }, `Saved. The on-screen rank, number or label changed on ${ns.length === 1 ? "shot" : "shots"} ${ns.join(", ")}. `,
      h("button", { class: "btn small", disabled: busy, onclick: () => { S.afterSave.overlay = []; runStep(run, "assemble"); } }, "Assemble again to see it")));
  }
  if (S.afterSave && S.afterSave.run === run.run_id && S.afterSave.voice.length) {
    const ns = S.afterSave.voice;
    panel.append(h("div", { class: "notice" }, `Saved. Lines changed on ${ns.length === 1 ? "shot" : "shots"} ${ns.join(", ")}. `,
      h("button", { class: "btn small", disabled: busy, onclick: () => { S.afterSave.voice = []; runStep(run, "voice", ns); } }, "Redo voice for them")));
  }
  if (S.afterSave && S.afterSave.run === run.run_id && (S.afterSave.images || []).length) {
    const ns = S.afterSave.images;
    panel.append(h("div", { class: "notice" }, `Saved. The picture changed on ${ns.length === 1 ? "shot" : "shots"} ${ns.join(", ")}. `,
      h("button", { class: "btn small", disabled: busy, onclick: () => { S.afterSave.video = [...new Set([...(S.afterSave.video || []), ...ns])].sort((a, b) => a - b); S.afterSave.images = []; runStep(run, "images", ns); } }, "Redo the images"),
      h("div", { class: "field-note" }, "Their clips are made from the old images, so redo the video for them afterwards.")));
  }
  if (S.afterSave && S.afterSave.run === run.run_id && (S.afterSave.video || []).length && !(S.afterSave.images || []).length) {
    const ns = S.afterSave.video;
    panel.append(h("div", { class: "notice" }, `${ns.length === 1 ? "Shot" : "Shots"} ${ns.join(", ")}: the clip no longer matches the script. `,
      h("button", { class: "btn small", disabled: busy, onclick: () => { S.afterSave.video = []; runStep(run, "video", ns); } }, "Redo the video for them")));
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
  const differs = (key) => changed.filter((n) => {
    const a = S.draft.shots.find((s) => s.n === n), b = run.script.shots.find((s) => s.n === n) || {};
    return (a[key] || "").trim() !== (b[key] || "").trim();
  });
  const sceneChanged = changed.filter((n) => {
    const a = S.draft.shots.find((s) => s.n === n), b = run.script.shots.find((s) => s.n === n) || {};
    return (a.same_scene === true) !== (b.same_scene === true);
  });
  const images = [...new Set([...differs("image_prompt"), ...sceneChanged])].sort((a, b) => a - b);
  const sound = differs("sfx");
  const overlay = changed.filter((n) => {
    const a = S.draft.shots.find((s) => s.n === n), b = run.script.shots.find((s) => s.n === n) || {};
    return JSON.stringify(a.stat ?? null) !== JSON.stringify(b.stat ?? null) || (a.label || "") !== (b.label || "");
  });
  const screen = [...new Set([...differs("app_screen"), ...changed.filter((n) => {
    const a = S.draft.shots.find((s) => s.n === n), b = run.script.shots.find((s) => s.n === n) || {};
    return (a.app_still === true) !== (b.app_still === true);
  })])].sort((a, b) => a - b);
  const clipped = new Set(run.shots.filter((s) => s.shot.animate || s.shot.talk).map((s) => s.n));
  const video = differs("motion_prompt").filter((n) => clipped.has(n) && !images.includes(n));
  try {
    await api("PUT", `/api/runs/${encodeURIComponent(run.run_id)}/script`, S.draft);
    S.saveErrors = null;
    S.afterSave = { run: run.run_id, voice, images, sound, overlay, screen, video: [...video, ...images.filter((n) => clipped.has(n))].sort((a, b) => a - b) };
    toast("Script saved", "ok");
    await loadRun(run.run_id, { keepDraft: false });
  } catch (e) {
    S.saveErrors = (e.detail && e.detail.errors ? e.detail.errors : [e.message])
      .map((m) => m.replace(/shots\[(\d+)\]/g, (_, i) => `shot #${Number(i) + 1}`)
        .replace(/characters\[(\d+)\]/g, (_, i) => `character ${Number(i) + 1}`));
    renderMain();
  }
}

// ------------------------------------------------------------ characters
function renderChars() {
  const cards = S.chars.map((c) => h("a", { class: "ccard", href: `#/characters/${encodeURIComponent(c.id)}`, title: c.description },
    h("div", { class: "ccard-img" }, c.image ? h("img", { src: c.image, alt: "", loading: "lazy" })
      : h("span", { class: "ccard-none" }, c.name.slice(0, 1).toUpperCase()),
      c.keep_as_is ? h("span", { class: "fcard-tag" }, "As is") : null),
    h("div", { class: "ccard-body" }, h("div", { class: "fcard-title" }, c.name),
      c.role ? h("div", { class: "ccard-role" }, c.role) : null,
      h("div", { class: "fcard-desc" }, c.description))));
  $("#main").replaceChildren(h("div", { class: "view studio" },
    h("div", { class: "studio-head" },
      h("div", {}, h("h1", {}, "Characters"),
        h("p", { class: "lede" }, "Make a character once, then cast it in any format: it can take over a format's role or join the story.")),
      h("span", { class: "muted", style: "font-size:12px" }, plural(S.chars.length, "character"))),
    h("div", { class: "cgrid" },
      h("a", { class: "ccard new", href: "#/characters/new" },
        h("div", { class: "ccard-img" }, h("span", { class: "ccard-plus" }, "+")),
        h("div", { class: "ccard-body" }, h("div", { class: "fcard-title" }, "New character"),
          h("div", { class: "fcard-desc" }, "Describe one and draw it, or upload a picture."))),
      cards)));
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result); r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function renderCharEditor(cid) {
  const isNew = cid === "new";
  const c = isNew ? null : S.chars.find((x) => x.id === cid);
  if (!isNew && !c) {
    $("#main").replaceChildren(h("div", { class: "empty" }, S.charsLoaded ? `No character "${cid}". ` : "Loading…",
      h("a", { href: "#/characters", class: "muted" }, "Back to Characters")));
    return;
  }
  const st = { upload: null, uploadName: "", drawFormat: (c && c.drawn_in) || (S.formats.find((f) => f.default) || {}).name || "pixar_arc" };
  const name = h("input", { type: "text", maxlength: "60", value: c ? c.name : "", placeholder: "Dana", id: "c-name" });
  const desc = h("textarea", { rows: "4", maxlength: "400", id: "c-desc",
    placeholder: "a 30 year old woman with short black hair, warm brown skin, freckles, a slim build" }, c ? c.description : "");
  const role = h("input", { type: "text", maxlength: "80", value: c ? c.role : "", placeholder: "the hero (optional)" });
  const voice = h("input", { type: "text", maxlength: "64", value: c ? c.voice_id : "", placeholder: "ElevenLabs voice id (optional)" });
  const voiceBox = h("div", { class: "voice-pick" });
  const drawVoice = () => {
    if (!S.voices || !S.voices.length) { voiceBox.replaceChildren(voice); return; }
    const play = h("button", { class: "icon-btn", type: "button", title: "Hear this voice", "aria-label": "Hear this voice",
      onclick: (e) => voice.value && playPreview(voice.value, e.currentTarget) }, "▶");
    voiceBox.replaceChildren(voiceSelect(voice.value, (id) => { voice.value = id; }, { label: "Voice", emptyLabel: "No voice of their own" }), play);
  };
  drawVoice();
  if (S.voices === null) loadVoices().then(drawVoice);
  const asIs = h("input", { type: "checkbox", checked: !!(c && c.keep_as_is) });
  const errBox = h("div");
  const preview = h("div", { class: "char-preview" });
  const drawPreview = () => {
    const src = st.upload || (c && c.image);
    preview.replaceChildren(src ? h("img", { src, alt: "" }) : h("div", { class: "char-preview-none" },
      h("span", {}, (name.value || "?").slice(0, 1).toUpperCase()), h("p", {}, "No picture yet. Upload one, or draw it from the description.")));
    if (st.upload) preview.append(h("span", { class: "example-tag" }, "Not saved yet"));
  };
  name.addEventListener("input", () => { if (!st.upload && !(c && c.image)) drawPreview(); });

  const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", class: "hidden",
    onchange: async (e) => {
      const fl = e.target.files[0]; if (!fl) return;
      if (fl.size > 15 * 1024 * 1024) { toast("That picture is over 15 MB.", "bad"); return; }
      st.upload = await readFile(fl); st.uploadName = fl.name; drawPreview();
    } });
  const body = () => ({ name: name.value, description: desc.value, role: role.value, voice_id: voice.value,
    keep_as_is: asIs.checked, image: st.upload });

  async function save(quiet) {
    try {
      const saved = isNew ? await api("POST", "/api/characters", body())
        : await api("PUT", `/api/characters/${encodeURIComponent(cid)}`, body());
      await loadChars();
      if (!quiet) toast(`Saved ${saved.name}`, "ok");
      st.upload = null;
      if (isNew) location.hash = `#/characters/${encodeURIComponent(saved.id)}`; else renderCharEditor(cid);
      return saved;
    } catch (e) {
      errBox.replaceChildren(h("div", { class: "notice bad" }, e.message));
      return null;
    }
  }
  const saveBtn = h("button", { class: "btn primary", type: "button", onclick: () => save(false) }, isNew ? "Create character" : "Save");

  const describeBtn = h("button", { class: "btn small", type: "button", onclick: async () => {
    if (!st.upload && !(c && c.image)) { toast("Upload a picture first.", "bad"); return; }
    const ok = await confirmDialog({ title: "Describe this picture?", ok: "Describe",
      text: "Claude looks at the picture and writes a one-sentence description of who it is (face, hair, skin, build). One short API call, about a cent." });
    if (!ok) return;
    describeBtn.disabled = true; describeBtn.textContent = "Looking…";
    try {
      const r = await api("POST", "/api/characters/describe", st.upload ? { image: st.upload } : { character: cid });
      desc.value = r.description; toast("Description written. Edit it if anything is off.", "ok");
    } catch (e) { toast(e.message, "bad"); }
    describeBtn.disabled = false; describeBtn.textContent = "Describe from picture";
  } }, "Describe from picture");

  const fmtSel = h("select", { "aria-label": "Style to draw in", onchange: (e) => { st.drawFormat = e.target.value; } },
    S.formats.filter((f) => !f.error).map((f) => h("option", { value: f.name, selected: f.name === st.drawFormat }, formatTitle(f))));
  const drawBtn = h("button", { class: "btn small", type: "button", onclick: async () => {
    if (!desc.value.trim() || !name.value.trim()) { toast("Give the character a name and a description first.", "bad"); return; }
    const f = S.formats.find((x) => x.name === st.drawFormat);
    const ok = await confirmDialog({ title: `Draw ${name.value.trim()}?`, ok: "Draw",
      rows: [[`1 image in the ${formatTitle(f)} style (${providerFor("images", "")})`, imageCost(1, "")]], total: imageCost(1, ""),
      text: "Draws a reference sheet from the description. It replaces the current picture. In other formats VidGen redraws it in that format's style." });
    if (!ok) return;
    const saved = await save(true);
    if (!saved) return;
    await submit(api("POST", `/api/characters/${encodeURIComponent(saved.id)}/draw`, { format: st.drawFormat }), `draw ${saved.name}`);
  } }, "Draw it");

  const del = !isNew ? h("button", { class: "btn ghost small danger", type: "button", onclick: async () => {
    const ok = await confirmDialog({ title: `Delete ${c.name}?`, ok: "Delete",
      text: "Removes the character and its picture from your library. Runs that already used it keep their copies." });
    if (!ok) return;
    try { await api("DELETE", `/api/characters/${encodeURIComponent(cid)}`); await loadChars(); toast(`Deleted ${c.name}`, "ok"); location.hash = "#/characters"; }
    catch (e) { toast(e.message, "bad"); }
  } }, "Delete") : null;

  const field = (label, el, note) => h("label", { class: "field" }, h("span", {}, label), el, note ? h("div", { class: "field-note" }, note) : null);
  const drawing = S.jobs.some((j) => j.action === "draw_character" && ACTIVE.has(j.status) && j.params.character === cid);
  $("#main").replaceChildren(h("div", { class: "view create" },
    h("a", { class: "back-link", href: "#/characters" }, icon("chevron-left", 14), "Characters"),
    h("h1", {}, isNew ? "New character" : c.name),
    h("p", { class: "lede" }, "The description is what every shot's prompt says about them, word for word. The picture keeps their look the same from shot to shot."),
    h("div", { class: "create-grid" },
      h("div", { class: "create-left" },
        h("section", { class: "card-sec stack" },
          field("Name", name),
          h("div", { class: "field" }, h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Description"), describeBtn), desc,
            h("div", { class: "field-note" }, "Who they are, not what they wear: age, face, hair, skin, build, one distinctive feature.")),
          field("Usual role", role, "Used when you add them to a story. When they replace a format's character they take that role."),
          h("div", { class: "field" }, h("span", {}, "Voice"), voiceBox,
            h("div", { class: "field-note" }, "Speaks their lines. None: the voice of the character they replace, or one cast for the video."))),
        h("section", { class: "card-sec" },
          h("div", { class: "sec-head" }, h("span", { class: "sec-label" }, "Picture")),
          h("div", { class: "pic-actions" },
            h("button", { class: "btn small", type: "button", onclick: () => file.click() }, (c && c.image) || st.upload ? "Upload a different picture" : "Upload a picture"), file),
          h("div", { class: "pic-actions" }, h("span", { class: "muted" }, "or draw it in"), fmtSel, drawBtn),
          h("label", { class: "check", style: "margin-top:10px" }, asIs, "Use my picture exactly as it is"),
          h("div", { class: "field-note" }, "Off: VidGen redraws the picture as a reference sheet in each format's style the first time it is used there (one image each). On: the picture itself is the reference, e.g. a sheet you already made.")),
        errBox,
        h("div", { class: "form-actions" }, saveBtn, del)),
      h("section", { class: "create-right" }, h("div", { class: "sec-label" }, "Picture"),
        h("div", { class: "example-wrap" }, preview,
          drawing ? h("p", { class: "example-note" }, h("span", { class: "spin" }), "  Drawing… this takes about half a minute.") : null,
          c && c.source ? h("p", { class: "example-note" }, c.source === "generated" ? `Drawn in the ${c.drawn_in || ""} style.` : "Uploaded picture.") : null)))));
  drawPreview();
  if (isNew) name.focus();
}

// ------------------------------------------------- Claude Code engine run
function storyChanged() {
  if (!S.run || !S.run.story || !S.storyDraft || S.storyFor !== S.run.run_id) return false;
  return JSON.stringify(S.storyDraft.beats) !== JSON.stringify(S.run.story.beats);
}

function renderCodeRun() {
  const run = S.run;
  const busy = runBusy(run.run_id);
  const active = S.jobs.find((j) => j.run_id === run.run_id && ACTIVE.has(j.status));
  const has = (k) => run.steps[k].status === "done";
  const next = !run.story ? "story" : !has("scenes") ? "scenes" : !has("voice") ? "voice" : !has("render") ? "render" : null;
  const stepBtns = [];
  CODE_STEPS.forEach((step, i) => {
    const st = run.steps[step];
    if (i) stepBtns.push(h("span", { class: `step-arrow${st.status === "done" ? " done" : ""}` }));
    stepBtns.push(h("button", { class: `step-btn ${st.status}${step === next ? " next" : ""}`,
      disabled: busy || (step !== "story" && !run.story),
      title: CODE_STEP_HELP[step], onclick: () => runCodeStep(run, step) },
      h("span", { class: "step-num" }, st.status === "done" ? icon("check", 12) : String(i + 1)),
      h("span", { class: "step-name" }, CODE_STEP_NAME[step]),
      st.note && st.note !== "claude" && st.note !== "voiced" ? h("span", { class: "count" }, st.note) : null));
  });
  const finalSrc = run.final_video ? bust(run.final_video, run.run_id) : null;
  const cta = !run.story
    ? h("button", { class: "btn primary cta", disabled: busy, onclick: () => runCodeStep(run, "story") }, h("span", {}, "Write the story"), icon("arrow-right"))
    : next ? h("button", { class: "btn primary cta", disabled: busy, onclick: () => runCodeRest(run, next) },
      h("span", {}, next === "scenes" ? "Code the scenes and render" : `Continue from ${CODE_STEP_NAME[next].toLowerCase()}`), icon("arrow-right"))
    : finalSrc ? h("a", { class: "btn primary cta", href: finalSrc, download: `${run.run_id}.mp4` }, icon("download"), h("span", {}, "Download video")) : null;
  const head = h("header", { class: "run-head" },
    h("div", { class: "run-top" },
      h("h1", { class: "run-title", title: run.premise || "" }, run.premise || run.run_id),
      cta),
    h("div", { class: "run-sub" },
      h("span", { class: "pill" }, formatName(run.format)),
      h("span", { class: "eng-pill" }, "Claude Code engine"),
      h("span", { class: "cost", title: run.cost.rows.map((r) => `${r.item}: ${usd(r.usd)}`).join("\n") }, `est. ${usd(run.cost.total)}`),
      h("span", { class: "dim" }, when(run.created_at)),
      busy ? h("span", { class: "busy-note" }, h("span", { class: `dot ${active.status}` }),
        `${active.action}${active.params.step ? ` ${active.params.step}` : ""} ${active.status}…`) : null),
    h("div", { class: "steps" }, stepBtns));

  const left = h("div", { class: "shots-col" });
  if (run.cast && run.cast.length) {
    left.append(h("div", { class: "panel-title" }, "Your characters in this run"),
      h("div", { class: "chars" }, run.cast.map((c) => h("div", { class: "char" },
        h("div", { class: "face", style: c.image ? `background-image:url("${c.image}")` : "" }, c.image ? "" : c.name.slice(0, 1)),
        c.name, c.replaced ? h("div", { class: "dim" }, `as ${c.replaced}`) : null))));
  }
  left.append(h("div", { class: "panel-title" }, `Stills${run.stills.length ? ` · ${run.stills.length}` : ""}`));
  left.append(run.stills.length ? h("div", { class: "grid" }, run.stills.map((p) =>
    h("a", { class: "shot", href: bust(p.url, run.run_id), target: "_blank", rel: "noopener", title: p.name },
      h("div", { class: "thumb" }, h("img", { src: bust(p.url, run.run_id), alt: p.name, loading: "lazy" }),
        h("div", { class: "badges" }, h("span", { class: "badge n" }, `${Number(p.name.replace(/^t/, "").replace(/\.jpg$/, "")) || 0}s`))))))
    : h("div", { class: "player-empty wide" }, run.story ? "Claude Code saves stills here while it codes the scenes." : "Write the story first."));
  if (run.story_notes) {
    left.append(h("details", { class: "card-sec notes" }, h("summary", {}, h("span", { class: "sec-label" }, "Claude's notes (story.md)"), h("span", { class: "muted" }, "Show")),
      h("pre", {}, run.story_notes)));
  }

  const final = h("section", { class: "side-card", "aria-label": "Final video" }, h("div", { class: "panel-title" }, "Final video"));
  if (run.final_video) {
    const src = bust(run.final_video, run.run_id);
    final.append(h("video", { class: "player", controls: true, playsinline: true, preload: "metadata", src }),
      h("div", { class: "final-actions" },
        h("a", { class: "btn small", href: src, download: `${run.run_id}.mp4` }, icon("download", 14), "Download"),
        h("a", { class: "btn small ghost", href: src, target: "_blank", rel: "noopener" }, "Open"),
        h("button", { class: "btn small ghost", onclick: () => setFormatMedia(run, "example"),
          title: "Show this video on the format's page as its example" }, "Use as example")));
  } else {
    final.append(h("div", { class: "player-empty" }, run.story ? "Not rendered yet. It appears here after the render step." : "No video yet."));
  }
  if (run.voice) final.append(h("audio", { class: "voice-player", controls: true, preload: "none", src: bust(run.voice, run.run_id) }));
  const side = h("aside", { class: "side-col" }, final);
  if (run.story) side.append(storyPanel(run, busy));
  if (run.cost.rows.length) {
    side.append(h("section", { class: "side-card", "aria-label": "Cost" }, h("div", { class: "panel-title" }, "Cost so far"),
      h("div", { class: "cost-rows" },
        run.cost.rows.map((r) => h("div", {}, h("span", {}, r.item), h("span", {}, usd(r.usd)))),
        h("div", { class: "total" }, h("span", {}, "Estimated total"), h("span", {}, usd(run.cost.total))))));
  }
  const main = $("#main");
  const scroll = main.scrollTop;
  main.replaceChildren(head, h("div", { class: "run-body" }, left, side));
  main.scrollTop = scroll;
}

const CODE_STEP_NAME = { story: "Story", scenes: "Scenes", voice: "Voice", render: "Render" };
const CODE_STEP_HELP = {
  story: "Claude Code writes the story (one line per beat)",
  scenes: "Claude Code codes every scene for this story and checks stills",
  voice: "Read the lines with ElevenLabs and time the beats to the voice",
  render: "Render the video on this computer (node render.cjs video)",
};

async function runCodeStep(run, step) {
  if (storyChanged() && step !== "story") { toast("Save or discard your story edits first.", "bad"); return; }
  const texts = {
    story: ["Rewrite the story?", "Claude Code writes a new story.json (your Claude plan). The scenes, voice and render then need to run again."],
    scenes: ["Code the scenes?", "Claude Code rewrites each style file for this story and checks stills. It runs on your Claude plan and can take 10-30 minutes."],
    voice: ["Redo the voice?", `Reads every line with ElevenLabs (about ${usd(voiceCost(run.story ? run.story.beats.map((b) => b.line).join(" ").length : 300))}) and retimes the beats.`],
    render: ["Render the video?", "Runs on this computer. The 3D styles render in software on Windows, so a 20 second video can take several minutes."],
  };
  const [title, text] = texts[step];
  if (!(await confirmDialog({ title, text, ok: "Run" }))) return;
  await submit(api("POST", `/api/runs/${encodeURIComponent(run.run_id)}/step`, { step }), `step ${step}`);
}

async function runCodeRest(run, from) {
  if (storyChanged()) { toast("Save or discard your story edits first.", "bad"); return; }
  const steps = CODE_STEPS.slice(CODE_STEPS.indexOf(from));
  const ok = await confirmDialog({ title: `Run ${steps.join(", ")}?`, ok: "Run",
    text: "Claude Code codes the scenes on your Claude plan, VidGen adds the voice (ElevenLabs) and renders on this computer. Each step is a job in the queue." });
  if (!ok) return;
  for (const step of steps) {
    const r = await submit(api("POST", `/api/runs/${encodeURIComponent(run.run_id)}/step`, { step }), `step ${step}`);
    if (!r) break;
  }
}

function storyPanel(run, busy) {
  const styles = run.styles && run.styles.length ? run.styles : [...new Set(run.story.beats.map((b) => b.style))];
  const changed = storyChanged();
  const total = S.storyDraft.beats.reduce((a, b) => a + (Number(b.seconds) || 0), 0);
  const refresh = () => { const ch = storyChanged(); save.disabled = busy || !ch; discard.disabled = !ch;
    secs.textContent = `${S.storyDraft.beats.reduce((a, b) => a + (Number(b.seconds) || 0), 0).toFixed(1)}s`; };
  const rows = S.storyDraft.beats.map((b, i) => h("div", { class: "srow" },
    h("span", { class: "num" }, `${i + 1}`),
    h("div", { class: "fields" },
      h("div", { class: "pair" },
        h("select", { "aria-label": `Beat ${i + 1} style`, disabled: styles.length < 2, onchange: (e) => { b.style = e.target.value; refresh(); } },
          styles.map((x) => h("option", { value: x, selected: x === b.style }, x))),
        h("input", { type: "text", inputmode: "decimal", value: String(b.seconds), "aria-label": `Beat ${i + 1} seconds`,
          oninput: (e) => { b.seconds = Number(e.target.value); refresh(); } })),
      h("textarea", { rows: "2", "aria-label": `Beat ${i + 1} line`, oninput: (e) => { b.line = e.target.value; refresh(); } }, b.line))));
  const save = h("button", { class: "btn primary small", disabled: busy || !changed, onclick: async () => {
    try {
      await api("PUT", `/api/runs/${encodeURIComponent(run.run_id)}/story`, S.storyDraft);
      S.storyErrors = null; toast("Story saved. Run Scenes (or Voice, if only words changed) and Render.", "ok");
      await loadRun(run.run_id, { keepDraft: false });
    } catch (e) {
      S.storyErrors = e.detail && e.detail.errors ? e.detail.errors : [e.message]; renderMain();
    }
  } }, "Save story");
  const discard = h("button", { class: "btn ghost small", disabled: !changed,
    onclick: () => { S.storyDraft = structuredClone(run.story); S.storyErrors = null; renderMain(); } }, "Discard");
  const secs = h("span", { class: "word-count" }, `${total.toFixed(1)}s`);
  return h("section", { class: "side-card story-card", "aria-label": "Story" },
    h("div", { class: "panel-title" }, h("span", {}, "Story"), h("span", { class: "dim" }, "one line per beat")),
    h("p", { class: "script-help" }, "Edit before the scenes are coded. The voice retimes the seconds to the reading."),
    S.storyErrors ? h("div", { class: "notice bad errors" }, h("b", {}, "Not saved"), h("ul", {}, S.storyErrors.map((e) => h("li", {}, e)))) : null,
    h("div", { class: "script-list" }, rows),
    h("div", { class: "script-actions" }, save, discard, secs));
}

// ---------------------------------------------------------------- drawer
function openDrawer(open) {
  const d = $("#drawer");
  d.classList.toggle("collapsed", !open);
  $("#drawer-toggle").replaceChildren(icon(open ? "chevron-down" : "chevron-up", 14));
  $("#drawer-toggle").setAttribute("aria-expanded", String(open));
  try { localStorage.setItem("vidgen.drawer", open ? "1" : "0"); } catch { /* private mode */ }
  if (open) scrollLog(true);
}

function jobLabel(j) {
  const what = j.action === "step" ? `step ${j.params.step}${j.params.only ? ` (${j.params.only})` : ""}`
    : j.action === "reroll" ? `reroll shot ${j.params.shot}`
    : j.action === "new" ? (j.params.dry_run ? (j.params.engine === "claude_code" ? "new (story only)" : "new (dry run)") : "new video")
    : j.action === "draw_character" ? `draw ${j.params.character}` : j.action;
  return what;
}
function runPremise(runId) {
  if (!runId) return "characters";
  const r = S.runs.find((x) => x.run_id === runId);
  return r ? r.premise : runId;
}

function renderDrawer() {
  const running = S.jobs.filter((j) => j.status === "running");
  const queued = S.jobs.filter((j) => j.status === "queued").reverse();
  const recent = S.jobs.filter((j) => !ACTIVE.has(j.status)).slice(0, 12);
  const sum = $("#drawer-summary");
  if (running.length) {
    sum.replaceChildren(...[h("span", { class: "dot running" }), h("b", {}, jobLabel(running[0])),
      h("span", { class: "muted" }, `· ${runPremise(running[0].run_id)}`),
      queued.length ? h("span", { class: "muted" }, `· ${queued.length} queued`) : null].filter(Boolean));
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
  const setTitle = (job) => title.replaceChildren(...[h("span", { class: `dot ${job.status === "done" ? "done" : job.status}` }),
    h("b", {}, jobLabel(job)), h("span", {}, `· ${runPremise(job.run_id)} · ${job.status}`),
    job.run_id ? h("a", { href: `#/run/${encodeURIComponent(job.run_id)}`, class: "muted", style: "margin-left:auto" }, "open run ›")
      : job.action === "draw_character" ? h("a", { href: `#/characters/${encodeURIComponent(job.params.character)}`, class: "muted", style: "margin-left:auto" }, "open character ›") : null,
  ].filter(Boolean));
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
  if (runId !== S.runId) { S.selected.clear(); S.saveErrors = null; S.afterSave = null; S.draft = null; S.draftFor = null; S.run = null;
    S.storyDraft = null; S.storyFor = null; S.storyErrors = null; }
  S.runId = runId;
  renderSidebar();
  const nf = location.hash.match(/^#\/new\/(.+)$/);
  const ch = location.hash.match(/^#\/characters(?:\/(.+))?$/);
  const link = $("#screens-link"); if (link) link.classList.toggle("active", location.hash === "#/screens");
  if (runId) {
    if (!S.run) $("#main").replaceChildren(h("div", { class: "empty" }, h("span", { class: "spin" }), "  Loading…"));
    loadRun(runId);
  } else if (nf) {
    renderCreate(decodeURIComponent(nf[1]));
  } else if (ch) {
    if (ch[1]) renderCharEditor(decodeURIComponent(ch[1])); else renderChars();
  } else if (location.hash === "#/screens") {
    renderScreens();
  } else {
    renderStudio();
  }
  $("#main").focus({ preventScroll: true });
}

function renderMain() {
  if (S.runId && S.run && S.run.run_id === S.runId) renderRun();
}

window.addEventListener("beforeunload", (e) => {
  if (draftChanged().size || storyChanged()) { e.preventDefault(); e.returnValue = ""; }
});
// Ctrl+S / Cmd+S saves the script while it has unsaved changes.
window.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s" && S.run && S.draft && draftChanged().size && !runBusy(S.run.run_id)) {
    e.preventDefault();
    saveScript(S.run);
  }
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
