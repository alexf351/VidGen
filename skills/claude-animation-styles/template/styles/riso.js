// 09 RISOGRAPH. Two inks on off-white paper: each is its own halftone screen, printed slightly out of register.
import { canvas, clamp, ss, rng, easeOut, drawClaude, drawRocket, drawFlame, backOut } from '../lib/common.js'
const RH = 858 // the screen is computed at this size, then doubled with no smoothing so the dots stay crisp
const PAPER = [244, 238, 224], A = [255, 86, 62], B = [38, 66, 170] // fluoro orange, medium blue
const toneA = { star: .95, hood: 0, hoodDark: 0, jeans: 0, shoe: 0, body: .0, nose: 1, fin: 1, nozzle: .0, rim: 1, window: 0, flame1: 1, flame2: .7, flame3: .3 }
const toneB = { star: 0, hood: .85, hoodDark: 1, jeans: .62, shoe: 0, body: .06, nose: 0, fin: 0, nozzle: .7, rim: 0, window: .4, flame1: 0, flame2: 0, flame3: 0 }
export default {
  name: 'risograph',
  hero: 0.8,
  create({ W, H }) {
    this.W = W; this.H = H; const RW = (this.RW = Math.round(W / 2))
    const mk = () => { const c = canvas(RW, RH); return { c, x: c.getContext('2d', { willReadFrequently: true }) } }
    this.a = mk(); this.b = mk(); this.o = canvas(RW, RH); this.ox = this.o.getContext('2d'); this.img = this.ox.createImageData(RW, RH)
    // screens
    const scr = (ang, cell) => { const c = Math.cos(ang), s = Math.sin(ang), arr = new Float32Array(RW * RH); for (let y = 0; y < RH; y++) for (let x = 0; x < RW; x++) { const u = (x * c + y * s) / cell, v = (-x * s + y * c) / cell; arr[y * RW + x] = 0.5 + 0.25 * (Math.cos(u * 6.283) + Math.cos(v * 6.283)) } return arr }
    this.sa = scr(0.26, 4.3); this.sb = scr(1.31, 4.3)
    const r = rng(4), gr = new Float32Array(RW * RH); for (let i = 0; i < gr.length; i++) gr[i] = r(); this.gr = gr
  },
  render(t0, ctx, dur) {
    const f = Math.floor(t0 * 12), t = f / 12, u = t0 / dur, W = this.W, RW = this.RW
    const a = this.a.x, b = this.b.x
    // paint the same picture twice: a density map for each ink
    const both = (fn) => { fn(a, 0); fn(b, 1) }
    for (const l of [a, b]) { l.setTransform(0.5, 0, 0, 0.5, 0, 0); l.fillStyle = '#000'; l.fillRect(0, 0, W, 1716) }
    const g = (v) => { const k = Math.round(v * 255); return `rgb(${k},${k},${k})` }
    const shape = (build, va, vb) => { a.fillStyle = g(va); b.fillStyle = g(vb); const p = new Path2D(); build(p); a.fill(p); b.fill(p) }
    // sky: blue fading to nothing, with stars knocked out
    const skyB = b.createLinearGradient(0, 0, 0, 1200); skyB.addColorStop(0, g(0.74)); skyB.addColorStop(1, g(0.34)); b.fillStyle = skyB; b.fillRect(0, 0, W, 1300)
    const skyA = a.createLinearGradient(0, 300, 0, 1300); skyA.addColorStop(0, g(0)); skyA.addColorStop(1, g(0.28)); a.fillStyle = skyA; a.fillRect(0, 0, W, 1300)
    const sr = rng(6)
    for (let i = 0; i < 170; i++) { const x = sr() * W, y = sr() * 980, k = 2 + sr() * 5; b.fillStyle = '#000'; a.fillStyle = '#000'; b.beginPath(); b.arc(x, y, k, 0, 7); b.fill() }
    // the Earth, back where it came from: paper ring, deep blue sea, orange land
    const ex = W * 0.74, ey = 310
    shape((p) => p.arc(ex, ey, 152, 0, 7), 0, 0)
    a.save(); b.save()
    const disc = new Path2D(); disc.arc(ex, ey, 140, 0, 7); a.clip(disc); b.clip(disc)
    b.fillStyle = g(1); b.fillRect(ex - 160, ey - 160, 320, 320)
    const continents = new Path2D()
    for (const [cx, cy, rx, ry, ro] of [[-58, -66, 44, 24, 0.5], [-20, -34, 26, 18, 0.2], [58, -48, 26, 14, -0.4], [70, 6, 24, 40, -0.2], [52, 58, 15, 25, 0.3], [-62, 40, 32, 18, 0.1], [-34, 80, 20, 12, 0.5], [-88, 4, 13, 8, 0]]) { continents.moveTo(ex + cx + rx, ey + cy); continents.ellipse(ex + cx, ey + cy, rx, ry, ro, 0, 7) }
    a.fillStyle = g(0.95); a.fill(continents); b.fillStyle = g(0.15); b.fill(continents)
    a.restore(); b.restore()
    // moon surface: a big curve with craters
    const groundAt = (x) => 1300 - Math.pow((x - W / 2) / (W * 0.9), 2) * 300
    const moon = (p) => { p.moveTo(-10, groundAt(0)); for (let x = 0; x <= W + 24; x += 24) p.lineTo(x, groundAt(x)); p.lineTo(W + 10, 1730); p.lineTo(-10, 1730); p.closePath() }
    shape(moon, 0, 0)
    const gm = b.createLinearGradient(0, 1250, 0, 1716); gm.addColorStop(0, g(0.12)); gm.addColorStop(1, g(0.5)); b.fillStyle = gm; const mp = new Path2D(); moon(mp); b.fill(mp)
    const gm2 = a.createLinearGradient(0, 1250, 0, 1716); gm2.addColorStop(0, g(0.08)); gm2.addColorStop(1, g(0.38)); a.fillStyle = gm2; a.fill(mp)
    for (const [x0, y, k] of [[150, 1450, 74], [720, 1400, 52], [470, 1600, 96], [840, 1590, 72], [290, 1350, 32], [610, 1320, 26]]) {
      const x = (x0 * W) / 960
      b.fillStyle = g(0.8); b.beginPath(); b.ellipse(x, y, k, k * 0.36, 0, 0, 7); b.fill(); a.fillStyle = g(0.5); a.beginPath(); a.ellipse(x, y, k, k * 0.36, 0, 0, 7); a.fill()
      b.fillStyle = g(0.2); b.beginPath(); b.ellipse(x + 8, y + 6, k * 0.76, k * 0.24, 0, 0, 7); b.fill(); a.fillStyle = g(0.18); a.beginPath(); a.ellipse(x + 8, y + 6, k * 0.76, k * 0.24, 0, 0, 7); a.fill()
    }
    const paint = {
      fill(p, k) { a.fillStyle = g(toneA[k] ?? 0); b.fillStyle = g(toneB[k] ?? 0); a.fill(p); b.fill(p) },
      lines(segs, w, k) { for (const [l, tone] of [[a, toneA], [b, toneB]]) { l.strokeStyle = g(tone[k] ?? 0); l.lineCap = 'round'; l.lineWidth = w; l.beginPath(); segs.forEach((s) => { l.moveTo(s[0], s[1]); l.lineTo(s[2], s[3]) }); l.stroke() } },
    }
    // the rocket comes down, the engine cuts, Claude hops off and plants the flag
    const land = 0.42, s = 0.86, down = easeOut(u / land), rx = W / 2 + 190, gy = groundAt(rx)
    const tail = gy - 12, rocketY = tail - 306 * s - (1 - down) * 900
    drawFlame(paint, rx, rocketY + 306 * s, s, u < land ? 0.9 + Math.sin(t * 50) * 0.1 : 0, t)
    drawRocket(paint, rx, rocketY, s)
    // dust on touchdown
    if (u > land - 0.06 && u < 0.86) { const k = ss(land - 0.06, 0.8, u); for (let i = 0; i < 8; i++) { const sd = i % 2 ? 1 : -1, px = rx + sd * (60 + i * 42 * k), py = gy - 16 - i * 4 * k; a.fillStyle = g(0.5 * (1 - k * 0.6)); b.fillStyle = g(0.3 * (1 - k * 0.6)); const pp = new Path2D(); pp.arc(px, py, 44 * k + 20, 0, 7); a.fill(pp); b.fill(pp) } }
    const hop = ss(land + 0.04, 0.68, u), cx = rx - hop * 330, cy = hop < 1 ? (rocketY + 8) * (1 - hop) + groundAt(cx) * hop - Math.sin(hop * Math.PI) * 170 : groundAt(cx)
    const inFlight = hop > 0 && hop < 1, planted = u > 0.74
    const flagUp = backOut(ss(0.7, 0.86, u))
    if (u > 0.68) {
      const fx = cx - 118, fy = groundAt(fx) + 6, h = 330 * flagUp
      a.strokeStyle = g(0); b.strokeStyle = g(1); for (const l of [a, b]) { l.lineCap = 'round'; l.lineWidth = 10; l.beginPath(); l.moveTo(fx, fy); l.lineTo(fx, fy - h); l.stroke() }
      if (flagUp > 0.6) {
        const wv = Math.sin(t * 9) * 12
        shape((p) => { p.moveTo(fx, fy - h); p.quadraticCurveTo(fx - 70, fy - h + 26 + wv, fx - 170, fy - h + 10); p.lineTo(fx - 170, fy - h + 118); p.quadraticCurveTo(fx - 70, fy - h + 130 - wv, fx, fy - h + 108); p.closePath() }, 0.05, 0)
        // a tiny starburst on the flag
        const hx = fx - 86, hy = fy - h + 62; a.strokeStyle = g(1); a.lineWidth = 11; a.lineCap = 'round'; for (let i = 0; i < 8; i++) { const an = (i * Math.PI) / 4; a.beginPath(); a.moveTo(hx, hy); a.lineTo(hx + Math.cos(an) * 34, hy + Math.sin(an) * 34); a.stroke() }
      }
    }
    drawClaude(paint, cx, cy, 0.96, inFlight ? { armL: -150, armR: -30, legL: 26, legR: -26 } : planted ? { armL: 176, armR: -48 + Math.sin(t * 12) * 16, legL: 6, legR: -6, headTilt: Math.sin(t * 8) * 6 } : { armL: 150, armR: 30 })
    // shoe outlines read better knocked out of the blue
    // ------ print it ------
    const da = a.getImageData(0, 0, RW, RH).data, db = b.getImageData(0, 0, RW, RH).data
    const out = this.img.data, sa = this.sa, sb = this.sb, gr = this.gr, off = 2 // out of register by 2 px (4 on screen)
    const gs = (f * 2311) % (RW * RH)
    for (let y = 0; y < RH; y++) for (let x = 0; x < RW; x++) {
      const i = y * RW + x
      const xb = Math.min(RW - 1, x + off), yb = Math.min(RH - 1, y + 1), ib = yb * RW + xb
      const dA = da[i * 4] / 255, dB = db[ib * 4] / 255
      const n = gr[(i + gs) % gr.length], n2 = gr[(i * 3 + gs) % gr.length]
      const inkA = dA > 0.02 && dA * 1.08 + (n - 0.5) * 0.16 > sa[i] ? 0.94 + n * 0.06 : 0
      const inkB = dB > 0.02 && dB * 1.08 + (n2 - 0.5) * 0.16 > sb[i] ? 0.92 + n2 * 0.08 : 0
      // overprint: inks multiply, like real ones
      const px = i * 4
      for (let c = 0; c < 3; c++) out[px + c] = PAPER[c] * (1 - inkA * (1 - A[c] / 255)) * (1 - inkB * (1 - B[c] / 255))
      out[px + 3] = 255
    }
    this.ox.putImageData(this.img, 0, 0)
    ctx.imageSmoothingEnabled = false; ctx.drawImage(this.o, 0, 0, this.W, this.H); ctx.imageSmoothingEnabled = true
  },
}
