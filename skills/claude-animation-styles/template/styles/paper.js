// 06 PAPER CUTOUT. Every piece is cut card with a little shadow under it. Moves in steps, 8 poses a second, pinned at the joints.
import { canvas, clamp, ss, rng, drawClaude, drawRocket, drawFlame, lerp } from '../lib/common.js'
const PAL = { star: '#d97757', hood: '#42424a', hoodDark: '#33333a', jeans: '#3f6390', shoe: '#f7f3ea', body: '#f6f1e6', nose: '#d4412f', fin: '#d4412f', nozzle: '#5a5a62', rim: '#d4412f', window: '#8bc9e6', flame1: '#ea5b2a', flame2: '#f6a524', flame3: '#fde98a' }
export default {
  name: 'paper cutout',
  hero: 0.34,
  create({ W, H }) {
    this.W = W; this.H = H
    // paper fibre: drawn once, laid over the whole frame
    const g = (this.fibre = canvas(W, H)), x = g.getContext('2d'), r = rng(31)
    for (let i = 0; i < W * 27; i++) { const v = r() > 0.5 ? 255 : 0; x.fillStyle = `rgba(${v},${v},${v},${0.018 + r() * 0.028})`; x.fillRect(r() * W, r() * H, 1 + r() * 2, 1 + r() * 2) }
    for (let i = 0; i < W * 1.5; i++) { x.strokeStyle = `rgba(${r() > 0.5 ? '255,255,255' : '60,40,30'},${0.03 + r() * 0.05})`; x.lineWidth = 0.7; const a = r() * W, b = r() * H, ang = r() * 6.28, l = 8 + r() * 26; x.beginPath(); x.moveTo(a, b); x.lineTo(a + Math.cos(ang) * l, b + Math.sin(ang) * l); x.stroke() }
  },
  render(t0, ctx, dur) {
    const { W, H } = this, x = ctx
    const f = Math.floor(t0 * 8), t = f / 8, jr = rng(f * 11 + 1)
    const piece = (color, build, lift = 9) => { x.save(); x.shadowColor = 'rgba(30,18,40,.42)'; x.shadowBlur = lift * 1.6; x.shadowOffsetX = lift * 0.45; x.shadowOffsetY = lift * 0.8; x.fillStyle = color; const p = new Path2D(); build(p); x.fill(p); x.restore() }
    // Sky made of paper strips, dusk going dark as we climb
    const strips = ['#1e2a5e', '#2b2f70', '#44357e', '#6a3f86', '#9a4b82', '#cf6a70', '#ee9460', '#f6b878']
    const drop = ss(0.38, 1, t0 / dur) // after the engine dies everything starts falling back
    const scroll = (t * 180) * (1 - drop) - drop * 150
    const sh = H / strips.length
    strips.forEach((c, i) => {
      const y = i * sh - 30 + (scroll * 0.1) % 8
      piece(c, (p) => { p.moveTo(-20, y); let px = -20; const r = rng(i * 7 + 3); while (px < W + 40) { px += 40 + r() * 60; p.lineTo(px, y + (r() - 0.5) * 16) } p.lineTo(W + 40, H + 40); p.lineTo(-20, H + 40); p.closePath() }, 5)
    })
    // stars hung on threads
    const sr = rng(5)
    for (let i = 0; i < W / 110; i++) {
      const sx = 60 + sr() * (W - 120), len = 90 + sr() * 300, swing = Math.sin(t * 2 + i) * 0.05, k = 15 + sr() * 16
      x.save(); x.translate(sx, -10); x.rotate(swing)
      x.strokeStyle = 'rgba(255,255,255,.55)'; x.lineWidth = 2; x.beginPath(); x.moveTo(0, 0); x.lineTo(0, len); x.stroke()
      x.translate(0, len + k)
      piece('#fbe9a6', (p) => { for (let j = 0; j < 10; j++) { const a = (j / 10) * Math.PI * 2 - Math.PI / 2, r = j % 2 ? k * 0.45 : k; p[j ? 'lineTo' : 'moveTo'](Math.cos(a) * r, Math.sin(a) * r) } p.closePath() }, 5)
      x.restore()
    }
    // a paper plane line and clouds, layered, sliding past
    const cloud = (cx, cy, k, col, lift) => piece(col, (p) => { const rr = rng(Math.round(cx * 3 + cy)); p.moveTo(cx - 190 * k, cy + 44 * k); const n = 5; for (let i = 0; i < n; i++) { const u = i / (n - 1), bx = cx - 150 * k + u * 300 * k, r = (58 + rr() * 44) * k; p.arc(bx, cy + 4 * k - (i % 2 ? 26 : 0) * k, r, Math.PI, 0) } p.lineTo(cx + 190 * k, cy + 44 * k); p.closePath() }, lift)
    const layers = [[0.34, '#c9a6c9', 0.72, 6], [0.62, '#e7cfd8', 1.0, 9], [1.0, '#fbf3e7', 1.35, 14]]
    layers.forEach(([sp, col, k, lift], li) => {
      const rr = rng(li * 17 + 2)
      for (let i = 0; i < Math.max(6, W / 200); i++) {
        const cy = ((rr() * 2600 + scroll * sp * 2.4) % 2300) - 300
        const cx = rr() * W
        cloud(cx, cy, k * (0.85 + rr() * 0.4), col, lift)
      }
    })
    // the hero, pinned at joints. Engine out: it tilts, drops and Claude panics
    const died = t0 / dur > 0.3, sp = ss(0.14, 0.5, t0 / dur)
    const tilt = died ? lerp(0, -9, ss(0.3, 0.9, t0 / dur)) + (jr() - 0.5) * 1.5 : (jr() - 0.5) * 0.8
    const hx = W / 2 + (jr() - 0.5) * 3 + sp * 18, base = 800 + ss(0.42, 1, t0 / dur) * 200 + (jr() - 0.5) * 3
    const paint = {
      fill(p, k) { x.save(); x.shadowColor = 'rgba(30,18,40,.45)'; x.shadowBlur = 11; x.shadowOffsetX = 4; x.shadowOffsetY = 8; x.fillStyle = PAL[k]; x.fill(p); x.restore() },
      lines(segs, w, k) { x.save(); x.shadowColor = 'rgba(30,18,40,.45)'; x.shadowBlur = 11; x.shadowOffsetX = 4; x.shadowOffsetY = 8; x.strokeStyle = PAL[k]; x.lineCap = 'round'; x.lineWidth = w; x.beginPath(); segs.forEach((s) => { x.moveTo(s[0], s[1]); x.lineTo(s[2], s[3]) }); x.stroke(); x.restore() },
    }
    const s = 1.02, r = (tilt * Math.PI) / 180, tail = [hx - Math.sin(r) * 306 * s * -1, base + Math.cos(r) * 306 * s]
    drawFlame(paint, tail[0], tail[1], s, Math.max(0, 1.1 - sp * 1.5) * (0.82 + jr() * 0.3), t, tilt)
    // smoke puffs when it coughs out
    if (t0 / dur > 0.18) for (let i = 0; i < 5; i++) {
      const u = clamp(t0 / dur - 0.18 - i * 0.06) * 1.8
      if (u <= 0 || u >= 1) continue
      const pr = 34 + u * 44 + i * 4
      const sx = [-70, 58, -22, 96, -104][i], sy = [40, 120, 210, 300, 372][i]
      piece(i % 2 ? '#a79fb0' : '#8f8796', (p) => { p.arc(tail[0] + sx * (0.5 + u * 0.7), tail[1] + sy * u + 24, pr, 0, 7) }, 6)
    }
    drawRocket(paint, hx, base, s, { tilt })
    const wave = Math.sin(t * 22) * (died ? 34 : 6)
    drawClaude(paint, hx + Math.sin(r) * -6, base + 8, 1.12 * s, { armL: -150 + wave, armR: -30 - wave, legL: died ? 16 : 7, legR: died ? -16 : -7, lean: tilt * 0.8, headTilt: died ? wave * 0.4 : 0 })
    // brass split pins at the joints
    x.drawImage(this.fibre, 0, 0)
  },
}
