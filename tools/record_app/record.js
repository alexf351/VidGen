// Records a moment of the Iro app as frames, for VidGen's moving app screens
// (assets/screens/<name>.mp4). See README.md in this folder.
//   node record.js <outDir> <name> <route> '<job json>'
// It serves the app's dev web export, opens the route at phone size (430 x 932 at 2x) and
// steps a virtual clock one video frame at a time, taking a screenshot after each step. So
// every frame is fully drawn however slow the machine is, and the result is smooth at 30 fps.
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const REPO = process.env.IRO_REPO || path.resolve(process.cwd());   // the Iro app repo (for the still posters)
const DEPS = process.env.CAPTURE_DEPS || path.join(require('os').tmpdir(), 'iro-capture-deps');
const { chromium } = require(path.join(DEPS, 'node_modules/playwright-core'));

const WEB = process.env.CAPTURE_WEB || path.join(require('os').tmpdir(), 'iro-capture-web');
const FONTS = path.join(DEPS, 'node_modules/@fontsource');
const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.woff': 'font/woff', '.mp4': 'video/mp4', '.mp3': 'audio/mpeg' };

function serve(port) {
  return new Promise((res) => {
    const srv = http.createServer((req, resp) => {
      const u = decodeURIComponent(req.url.split('?')[0]);
      let f = u.startsWith('/__fonts/') ? path.join(FONTS, u.slice(9)) : path.join(WEB, u);
      if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) f = path.join(WEB, 'index.html');
      resp.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream', 'Access-Control-Allow-Origin': '*' });
      if (f.endsWith('index.html')) { resp.end(fs.readFileSync(f, 'utf8').replace('shrink-to-fit=no', 'shrink-to-fit=no, viewport-fit=cover')); return; }
      fs.createReadStream(f).pipe(resp);
    }).listen(port, () => res(srv));
  });
}

// Map the family names react-native-web's system stack asks for onto Inter
// (Latin) + Noto Sans SC (CJK, unicode-range split by fontsource).
function fontCss() {
  const fams = ['-apple-system', 'BlinkMacSystemFont', 'system-ui', 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', 'Helvetica Neue', 'sans-serif-fake'];
  let css = '';
  // CJK first: for a character both cover (curly quotes, apostrophes) the LATER face wins,
  // so Inter must come after or French ’ renders as a full-width CJK glyph.
  // Noto Sans SC: reuse fontsource's own split CSS but renamed onto the same families.
  for (const w of [400, 500, 700, 800, 900]) {
    const f = path.join(FONTS, 'noto-sans-sc', `${w}.css`);
    if (!fs.existsSync(f)) continue;
    const src = fs.readFileSync(f, 'utf8').replace(/url\(\.\/files\//g, 'url(/__fonts/noto-sans-sc/files/');
    for (const fam of fams) css += src.replace(/font-family:\s*'Noto Sans SC'/g, `font-family:"${fam}"`) + '\n';
  }
  for (const w of [400, 500, 600, 700, 800, 900]) {
    for (const fam of fams) {
      css += `@font-face{font-family:"${fam}";font-weight:${w};src:url(/__fonts/inter/files/inter-latin-${w}-normal.woff2) format("woff2");unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;}\n`;
      css += `@font-face{font-family:"${fam}";font-weight:${w};src:url(/__fonts/inter/files/inter-latin-ext-${w}-normal.woff2) format("woff2");unicode-range:U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF;}\n`;
    }
  }
  // Expo's dev-only error toast (a shadow-DOM host) never ships; keep it out of captures.
  css += '#error-toast{display:none !important}\n';
  return css;
}


// node record.js <outDir> <name> <route> <jobJson>
// Records one app moment frame by frame on a virtual clock, so every frame is rendered in full
// however slow this machine is. jobJson: {
//   ready: "text that must be on screen before recording starts" (optional),
//   boot: "real" | "stepped"   real: the page loads in real time, then the clock is paused and
//         the actions start the animation. stepped: the clock is paused before the page loads
//         and the app boots on stepped time, so an animation that starts by itself is caught
//         from its first frame.
//   lead: ms of stepped time to run after ready and before recording (stepped boot), default 0
//   ms: length to record, fps: default 30,
//   actions: [{at: ms, tap: "text"} | {at, tapLabel: "aria label regex"} | {at, wheel: dy} | {at, tapXY: [x, y]}]
// }
async function main() {
  const [outDir, name, route, jobJson] = process.argv.slice(2);
  const job = JSON.parse(jobJson || '{}');
  const fps = job.fps || 30, total = Math.round((job.ms || 4000) * fps / 1000);
  const frames = path.join(outDir, name); fs.rmSync(frames, { recursive: true, force: true }); fs.mkdirSync(frames, { recursive: true });
  const port = 8200 + Math.floor(Math.random() * 500);
  const srv = await serve(port);
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ['--no-sandbox'] });
  const css = fontCss() + (job.css || '');
  const seed = JSON.parse(process.env.SEED || '{}');
  const lang = 'en';
  try {
    const ctx = await browser.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2, locale: 'en' });
    await ctx.addInitScript(({ lang, seed, css, keepSplash, hideText }) => {
      try {
        if (!sessionStorage.getItem('seeded')) {
          localStorage.clear();
          localStorage.setItem('kiro-game-store', JSON.stringify(Object.assign({
            appLanguage: lang, courseLanguage: lang, onboarded: true, xp: 4109, streak: 45, xpScaleV2: true, isPro: true,
            hasSeenTabWalkthrough: true, tabIntroDone: true, firstHomeVisit: false, dailyGoalMinutes: '5',
            hasSeenBatteryIntro: true, hasSeenBatteryProIntro: true, operatorIntroSeen: true, operatorMeetSeen: true,
          }, seed)));
          sessionStorage.setItem('seeded', '1');
        }
      } catch (e) {}
      const add = () => {
        const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
        const hide = () => {
          for (const el of document.querySelectorAll('div')) {
            if (el.childElementCount !== 0 || !/was called without|Warning:|Possible unhandled/.test(el.textContent || '')) continue;
            let box = el;
            while (box.parentElement && box.parentElement.getBoundingClientRect().height < 160 && box.parentElement !== document.body) box = box.parentElement;
            box.style.visibility = 'hidden';
          }
        };
        // The app's boot splash covers the first two seconds of any screen. Unless the clip is
        // about opening the app, take it out of the picture so the screen's own entrance shows.
        const hideSplash = () => {
          for (const el of document.querySelectorAll('div')) {
            if (el.childElementCount !== 0 || (el.textContent || '').trim() !== 'Iro AI') continue;
            let box = el, best = null;
            while (box.parentElement && box.parentElement.id !== 'root' && (box.parentElement.textContent || '').trim() === 'Iro AI') {
              box = box.parentElement;
              const pos = getComputedStyle(box).position;
              if (pos === 'absolute' || pos === 'fixed') best = box;
            }
            if (best) best.style.display = 'none';
          }
        };
        // Dev-only controls on preview routes never ship; take them out of the picture.
        const hideDev = () => {
          for (const el of document.querySelectorAll('div')) {
            if (el.childElementCount !== 0 || !hideText.includes((el.textContent || '').trim())) continue;
            let box = el;
            while (box.parentElement && box.parentElement.getBoundingClientRect().height < 60 && box.parentElement.getBoundingClientRect().width < 200) box = box.parentElement;
            box.style.visibility = 'hidden';
          }
        };
        new MutationObserver(() => { hide(); hideDev(); if (!keepSplash) hideSplash(); }).observe(document.body || document.documentElement, { childList: true, subtree: true });
      };
      if (document.head) add(); else document.addEventListener('DOMContentLoaded', add);
    }, { lang, seed, css, keepSplash: !!job.splash, hideText: job.hideText || [] });
    const page = await ctx.newPage();
    const cdp = await ctx.newCDPSession(page);
    await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { top: 59, bottom: 34, left: 0, right: 0 } });
    await page.route('**/*.supabase.co/**', (r) => {
      const u = r.request().url();
      if (/\/storage\/v1\/object\/public\/(path-covers|lesson-art)\//.test(u)) return r.continue().catch(() => r.abort());
      return r.abort();
    });
    // Animated WebP loops play on the wall clock, not the virtual one, so they would race.
    // Serve each one's still poster instead (same folder, <name>_still.png or _closed/_opened).
    if (job.stills !== false) await page.route(/\/assets\/.*\.webp(\?.*)?$/, async (r) => {
      const u = decodeURIComponent(new URL(r.request().url()).pathname);
      const m = u.match(/^\/assets\/(assets\/(?:ranks|reward|mascot\/behaviors|operator-icons)\/.*?)([^/.]+)\.[0-9a-f]{16,}\.webp$/);
      if (!m) return r.continue();
      const dir = path.join(REPO, m[1]);
      for (const cand of [`${m[2]}_still.png`, `${m[2].replace(/_open$/, '_closed')}.png`]) {
        const f = path.join(dir, cand);
        if (fs.existsSync(f)) return r.fulfill({ status: 200, contentType: 'image/png', body: fs.readFileSync(f) });
      }
      return r.continue();
    });
    const errs = [];
    page.on('pageerror', (e) => errs.push(String(e).slice(0, 200)));
    await page.clock.install();
    const step = async (ms) => { await page.clock.runFor(ms); };
    const settle = () => page.waitForTimeout(job.settle || 30);
    const has = async (txt) => (await page.getByText(txt, { exact: false }).count()) > 0;
    if (job.boot === 'stepped') {
      await page.clock.pauseAt(new Date(Date.now() + 1000));
      await page.goto(`http://localhost:${port}${route}`, { waitUntil: 'load' });
      let waited = 0;
      // Boot on stepped time: small steps, real pauses in between for the network and React.
      while (waited < 60000) {
        await step(1000 / fps); await page.waitForTimeout(25); waited += 1000 / fps;
        if (job.ready ? await has(job.ready) : waited > 4000) break;
      }
      console.log('  booted on stepped time after', Math.round(waited), 'ms; ready:', job.ready ? await has(job.ready) : 'n/a');
      for (let t = 0; t < (job.lead || 0); t += 1000 / fps) { await step(1000 / fps); await page.waitForTimeout(10); }
    } else {
      await page.goto(`http://localhost:${port}${route}`, { waitUntil: 'load' });
      await page.waitForTimeout(Number(job.wait || 9000));
      if (job.ready && !(await has(job.ready))) console.log('  WARNING: ready text not on screen:', job.ready);
      for (const txt of job.pre || []) { await page.getByText(txt, { exact: true }).first().click({ force: true }).catch((e) => console.log('  pre tap failed', txt)); await page.waitForTimeout(900); }
      const now = await page.evaluate(() => Date.now());
      await page.clock.pauseAt(new Date(now + 200));
      await page.waitForTimeout(150);
    }
    await page.evaluate(() => document.fonts && document.fonts.ready);
    const actions = (job.actions || []).slice().sort((a, b) => a.at - b.at);
    const t0 = Date.now();
    for (let i = 0; i < total; i++) {
      const t = i * 1000 / fps;
      while (actions.length && actions[0].at <= t) {
        const a = actions.shift();
        if (a.tap) await page.getByText(a.tap, { exact: true }).first().click({ force: true, noWaitAfter: true }).catch((e) => console.log('  tap failed', a.tap, String(e).slice(0, 90)));
        else if (a.tapLabel) await page.getByRole('button', { name: new RegExp(a.tapLabel) }).first().click({ force: true, noWaitAfter: true }).catch((e) => console.log('  tap failed', a.tapLabel, String(e).slice(0, 90)));
        else if (a.tapXY) await page.mouse.click(a.tapXY[0], a.tapXY[1]);
        else if (a.wheel) { await page.mouse.move(215, 500); await page.mouse.wheel(0, a.wheel); }
        await settle();
      }
      await page.screenshot({ path: path.join(frames, `f${String(i).padStart(4, '0')}.jpg`), type: 'jpeg', quality: 94 });
      await step(1000 / fps); await settle();
    }
    console.log(name, '->', frames, `${total} frames in ${Math.round((Date.now() - t0) / 1000)}s`, errs.length ? `ERRORS ${errs.join(' | ')}` : 'ok');
    await ctx.close();
  } finally {
    await browser.close();
    srv.close();
  }
}
main().catch((e) => { console.error(e); process.exit(1); });
