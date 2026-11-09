// 03 COMIC ART. Ink outlines, flat colour, Ben-Day dots, action lines, a caption box and a BOOM you can read from space.
import { canvas, clamp, ss, rng, easeOut, backOut, easeIn, drawClaude, drawRocket, drawFlame } from '../lib/common.js'
const INK = '#14110f'
const PAL = { star: '#e8693c', hood: '#3f3f46', hoodDark: '#2c2c32', jeans: '#3b6db0', shoe: '#ffffff', body: '#ffffff', nose: '#e23a2a', fin: '#e23a2a', nozzle: '#55555c', rim: '#e23a2a', window: '#7fd4f7', flame1: '#f0442a', flame2: '#ffa31f', flame3: '#fff27a' }
function burst(x, cx, cy, R, r, n, seed) { const rn = rng(seed); x.beginPath(); for (let i = 0; i < n * 2; i++) { const a = (i / (n * 2)) * Math.PI * 2 - Math.PI / 2, k = i % 2 ? r * (0.85 + rn() * 0.3) : R * (0.82 + rn() * 0.32); x[i ? 'lineTo' : 'moveTo'](cx + Math.cos(a) * k, cy + Math.sin(a) * k) } x.closePath() }
export default {
  name: 'comic art',
  hero: 0.9,
  create({ W, H, words, start, end }) {
    this.wide = W / H > 1
    this.W = W; this.H = H
    // Land the countdown on the spoken words if there's narration, otherwise on even steps through the beat.
    const at = (w, frac) => { const k = (words || []).find((q) => q.w === w && q.t >= start - 0.01); return k ? k.t - start : frac * (end - start) }
    this.t3 = at('three', 0.04); this.t2 = at('two', 0.25); this.t1 = at('one', 0.46); this.tB = at('boom', 0.68)
    const d = (this.dots = canvas(26, 26)), dx = d.getContext('2d'); dx.fillStyle = 'rgba(255,255,255,.46)'; dx.beginPath(); dx.arc(6.5, 6.5, 4.6, 0, 7); dx.arc(19.5, 19.5, 4.6, 0, 7); dx.fill()
    const dk = (this.dotsDark = canvas(18, 18)), kx = dk.getContext('2d'); kx.fillStyle = 'rgba(20,17,15,.34)'; kx.beginPath(); kx.arc(4.5, 4.5, 3, 0, 7); kx.arc(13.5, 13.5, 3, 0, 7); kx.fill()
  },
  render(t, ctx, dur) {
    const { W, H } = this, x = ctx, B = this.tB
    const after = t - B, boom = after >= 0
    // shake on the blast
    const sh = boom ? Math.max(0, 1 - after / 0.55) * 26 : 0, rn = rng(Math.floor(t * 30))
    x.save(); x.translate((rn() - 0.5) * sh, (rn() - 0.5) * sh)
    // sky, dots
    x.fillStyle = boom ? '#fff06a' : '#59c1f2'; x.fillRect(-40, -40, W + 80, H + 80)
    if (boom) { x.fillStyle = '#ffb627'; x.beginPath(); x.arc(W / 2, H * 0.75, 1700, 0, 7); x.fill(); x.fillStyle = '#ffe04a'; x.beginPath(); x.arc(W / 2, H * 0.75, 1120, 0, 7); x.fill() }
    x.fillStyle = x.createPattern(this.dots, 'repeat'); x.fillRect(-40, -40, W + 80, H + 80)
    // action lines rush out from the rocket
    const cx = W / 2, cy = boom ? H * 0.55 : H * 0.62, lr = rng(Math.floor(t * 12) + 5)
    x.fillStyle = boom ? 'rgba(255,255,255,.75)' : 'rgba(255,255,255,.42)'
    const nl = boom ? 46 : 24
    for (let i = 0; i < nl; i++) {
      const a = (i / nl) * Math.PI * 2 + lr() * 0.09, w = 0.012 + lr() * 0.024, r0 = (boom ? 360 : 520) + lr() * 90
      x.beginPath(); x.moveTo(cx + Math.cos(a - w) * 2400, cy + Math.sin(a - w) * 2400); x.lineTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0); x.lineTo(cx + Math.cos(a + w) * 2400, cy + Math.sin(a + w) * 2400); x.fill()
    }
    // ground falls away after the blast
    const rise = boom ? easeIn(after / 0.9) * 980 + after * 260 : 0
    const gy = H * 0.84 + rise
    if (gy < H + 60) {
      x.fillStyle = '#3cb563'; x.strokeStyle = INK; x.lineWidth = 9
      x.beginPath(); x.moveTo(-40, gy + 20); x.quadraticCurveTo(W * 0.3, gy - 42, W * 0.6, gy + 6); x.quadraticCurveTo(W * 0.82, gy + 34, W + 40, gy - 14); x.lineTo(W + 40, H + 200); x.lineTo(-40, H + 200); x.closePath(); x.fill(); x.stroke()
      x.fillStyle = x.createPattern(this.dotsDark, 'repeat'); x.fill()
      // little house + fence silhouette for continuity
      x.fillStyle = '#e8e1cf'; x.lineWidth = 8; const hs = Math.max(0, W / 2 - 700); x.beginPath(); x.rect(hs + 70, gy - 170, 210, 160); x.fill(); x.stroke(); x.fillStyle = '#d0453b'; x.beginPath(); x.moveTo(hs + 36, gy - 166); x.lineTo(hs + 175, gy - 284); x.lineTo(hs + 314, gy - 166); x.closePath(); x.fill(); x.stroke(); x.fillStyle = '#ffd34d'; x.fillRect(hs + 104, gy - 134, 60, 60); x.strokeRect(hs + 104, gy - 134, 60, 60)
    }
    // the painter: thick ink under every piece
    const paint = {
      fill(p, k) { x.lineJoin = 'round'; x.strokeStyle = INK; x.lineWidth = 10; x.stroke(p); x.fillStyle = PAL[k]; x.fill(p) },
      lines(segs, w, k) {
        x.lineCap = 'round'; x.strokeStyle = INK; x.lineWidth = w + 15
        segs.forEach((s) => { x.beginPath(); x.moveTo(s[0], s[1]); x.lineTo(s[2], s[3]); x.stroke() })
        x.strokeStyle = PAL[k]; x.lineWidth = w
        segs.forEach((s) => { x.beginPath(); x.moveTo(s[0], s[1]); x.lineTo(s[2], s[3]); x.stroke() })
      },
    }
    // the hero: on the ground, shaking, then gone up the page
    const s = 1.24, rock = !boom ? ss(this.t3, B, t) : 0, tr = !boom ? Math.sin(t * 60) * rock * 6 : Math.sin(t * 40) * 4
    const heroX = W / 2 + tr
    const lift = boom ? -easeOut(after / 0.5) * 190 : 0
    const noseY = H * 0.84 - 306 * s - 2 + lift + (boom ? Math.sin(after * 6) * 12 : 0)
    const flame = boom ? 1.5 : ss(B - 1.1, B, t) * 0.24
    const tail = [heroX, noseY + 306 * s]
    drawFlame(paint, tail[0], tail[1], s, flame, t)
    const rk = drawRocket(paint, heroX, noseY, s)
    const a = boom ? -148 : -128 + rock * 14
    drawClaude(paint, heroX, noseY + 8, 1.06 * s, { armL: boom ? -158 : -150 + rock * 8, armR: boom ? -22 : -30 - rock * 8, legL: 7, legR: -7, headTilt: boom ? after * 90 : 0 })
    // smoke at the base once it blows
    if (boom || t > B - 0.9) {
      const pr = rng(8), grow = boom ? easeOut(after / 0.5) : ss(B - 0.9, B, t) * 0.28, base = gy - 16
      const puffs = []
      for (let i = 0; i < 40; i++) {
        const sd = i % 2 ? 1 : -1, sp = pr() * (W / 2 + 60), rad = (72 + pr() * 96) * grow
        puffs.push([W / 2 + sd * sp * grow, Math.min(base, H + 100) - pr() * 100 * grow - (boom ? after * 90 : 0), rad])
      }
      x.fillStyle = INK; puffs.forEach(([a, b, c]) => { x.beginPath(); x.arc(a, b, c + 9, 0, 7); x.fill() })
      x.fillStyle = '#ffffff'; puffs.forEach(([a, b, c]) => { x.beginPath(); x.arc(a, b, c, 0, 7); x.fill() })
      x.fillStyle = x.createPattern(this.dotsDark, 'repeat'); puffs.forEach(([a, b, c]) => { x.beginPath(); x.arc(a + c * 0.3, b + c * 0.34, c * 0.62, 0, 7); x.fill() })
    }
    x.restore()
    // caption box: 3, 2, 1
    if (!boom) {
      const n = t >= this.t1 ? '1' : t >= this.t2 ? '2' : t >= this.t3 ? '3' : ''
      x.save(); x.translate(56, 70); x.rotate(-0.02)
      x.fillStyle = '#fff27a'; x.strokeStyle = INK; x.lineWidth = 9; x.fillRect(0, 0, 382, 126); x.strokeRect(0, 0, 382, 126)
      x.fillStyle = INK; x.font = '76px Bangers, Impact, sans-serif'; x.textBaseline = 'middle'; x.fillText('LIFT-OFF IN...', 22, 66)
      x.restore()
      if (n) {
        const u = backOut(((t >= this.t1 ? t - this.t1 : t >= this.t2 ? t - this.t2 : t - this.t3)) / 0.22)
        x.save(); this.wide ? x.translate(W / 2 + 560, 560) : x.translate(W * 0.74, 390); x.scale(u * (this.wide ? 1 : 0.62), u * (this.wide ? 1 : 0.62)); x.rotate(0.05)
        x.font = '560px Bangers, Impact, sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.lineJoin = 'round'
        x.lineWidth = 44; x.strokeStyle = INK; x.strokeText(n, 0, 0); x.fillStyle = '#fff'; x.fillText(n, 0, 0)
        x.restore(); x.textAlign = 'left'
      }
    } else {
      // BOOM!
      const u = backOut(after / 0.26, 2.2), wob = Math.sin(after * 22) * 0.012
      x.save(); this.wide ? x.translate(W / 2 + 590, 470) : x.translate(W * 0.6, 232); const bs = this.wide ? 1.02 : 0.64; x.scale(u * bs, u * bs); x.rotate(-0.09 + wob)
      burst(x, 0, 0, 520, 300, 15, 4); x.fillStyle = INK; x.save(); x.translate(10, 16); x.fill(); x.restore()
      burst(x, 0, 0, 520, 300, 15, 4); x.fillStyle = '#e23a2a'; x.fill(); x.lineWidth = 14; x.strokeStyle = INK; x.stroke()
      burst(x, 0, 0, 430, 265, 15, 9); x.fillStyle = '#ffd31f'; x.fill()
      x.font = '256px Bangers, Impact, sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.lineJoin = 'round'
      x.lineWidth = 26; x.strokeStyle = INK; x.strokeText('BOOM!', 0, 8); x.fillStyle = '#fff'; x.fillText('BOOM!', 0, 8)
      x.restore(); x.textAlign = 'left'
    }
    // the panel border
    x.lineWidth = 16; x.strokeStyle = INK; x.strokeRect(8, 8, W - 16, H - 16)
  },
}
