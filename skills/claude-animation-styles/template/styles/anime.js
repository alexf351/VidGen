// 07 RETRO ANIME. 80s cel look: painted gradient sky, two-tone shading, speed lines, an impact frame on the kick, film grain.
import { canvas, clamp, ss, rng, easeOut, easeIn, drawClaude, drawRocket, drawFlame, lerp } from '../lib/common.js'
const PAL = { star: '#e8734a', hood: '#34324e', hoodDark: '#262440', jeans: '#2f5c9a', shoe: '#fdf6e8', body: '#f2eee6', nose: '#d93a48', fin: '#d93a48', nozzle: '#4a4866', rim: '#d93a48', window: '#67d0ef', flame1: '#3f9dff', flame2: '#a8e4ff', flame3: '#ffffff' }
const LINE = '#1a1430'
export default {
  name: 'retro anime',
  hero: 0.72,
  create({ W, H }) {
    this.W = W; this.H = H
    const sky = (this.sky = canvas(W, H)), x = sky.getContext('2d')
    const g = x.createLinearGradient(0, 0, 0, H); g.addColorStop(0, '#0e0a34'); g.addColorStop(0.42, '#3a1a6e'); g.addColorStop(0.72, '#b23d8d'); g.addColorStop(0.92, '#ff8a6e'); g.addColorStop(1, '#ffc98a'); x.fillStyle = g; x.fillRect(0, 0, W, H)
    const r = rng(12)
    for (let i = 0; i < W * 0.34; i++) { const y = r() * H * 0.7, k = r(); x.fillStyle = `rgba(255,${235 + k * 20},${220 + k * 35},${0.25 + k * 0.7})`; x.beginPath(); x.arc(r() * W, y, 0.8 + k * 2.2, 0, 7); x.fill() }
    // painted cloud bands at the bottom
    for (let i = 0; i < W * 0.027; i++) { const yy = H * 0.74 + r() * H * 0.28, w = 200 + r() * 420; x.fillStyle = `rgba(${255},${180 + r() * 60},${170 + r() * 50},${0.28 + r() * 0.22})`; x.beginPath(); x.ellipse(r() * W, yy, w, 12 + r() * 30, 0, 0, 7); x.fill() }
    const gr = (this.grain = canvas(256, 256)), gx = gr.getContext('2d'), n = rng(77); for (let i = 0; i < 256; i++) for (let k = 0; k < 256; k++) { const v = n() * 255; gx.fillStyle = `rgba(${v},${v},${v},.075)`; gx.fillRect(i, k, 1, 1) }
  },
  render(t, ctx, dur) {
    const { W, H } = this, x = ctx
    const kick = dur * 0.44, a = t - kick, hit = a >= 0
    const f2 = Math.floor(t * 12) / 12 // animate on twos, like a cel
    const rn = rng(Math.floor(t * 12) * 3 + 2)
    const shake = hit ? Math.max(0, 1 - a / 0.3) * 22 : 0
    x.save(); x.translate((rn() - 0.5) * shake, (rn() - 0.5) * shake)
    x.drawImage(this.sky, 0, hit ? -easeIn(a / 0.5) * 160 : 0)
    // a huge anime sun disc behind the hero
    x.fillStyle = '#ffd2a0'; x.beginPath(); x.arc(W * 0.5, H * 0.46, Math.min(500, W * 0.34), 0, 7); x.fill()
    x.fillStyle = '#ff8f7c'; for (let i = 0; i < 6; i++) { const R = Math.min(500, W * 0.34), y = H * 0.46 + R * 0.2 + i * R * 0.125, h = R * 0.018 + i * R * 0.01; x.fillRect(W * 0.5 - R * 1.04, y, R * 2.08, h) }
    x.save(); x.globalCompositeOperation = 'destination-over'; x.restore()
    // speed lines: tight bundle rushing to the centre after the kick
    if (hit) {
      x.strokeStyle = 'rgba(255,255,255,.86)'
      const cx = W / 2, cy = H * 0.42, n = 120
      for (let i = 0; i < n; i++) { const an = rn() * 6.283, r0 = 300 + rn() * 300, r1 = r0 + 700 + rn() * 1300; x.lineWidth = 1 + rn() * 6; x.beginPath(); x.moveTo(cx + Math.cos(an) * r0, cy + Math.sin(an) * r0); x.lineTo(cx + Math.cos(an) * r1, cy + Math.sin(an) * r1); x.stroke() }
    }
    const paint = {
      fill(p, k) { x.lineJoin = 'round'; x.strokeStyle = LINE; x.lineWidth = 6; x.stroke(p); x.fillStyle = PAL[k]; x.fill(p) },
      lines(segs, w, k) { x.lineCap = 'round'; x.strokeStyle = LINE; x.lineWidth = w + 11; segs.forEach((s) => { x.beginPath(); x.moveTo(s[0], s[1]); x.lineTo(s[2], s[3]); x.stroke() }); x.strokeStyle = PAL[k]; x.lineWidth = w; segs.forEach((s) => { x.beginPath(); x.moveTo(s[0], s[1]); x.lineTo(s[2], s[3]); x.stroke() }) },
    }
    // big dramatic framing: rocket fills the bottom, then rips upward
    const s = 1.5
    const windUp = ss(0, kick, t), rise = hit ? easeOut(a / 0.28) * -190 - a * 60 : windUp * 34
    const hx = W / 2 + (hit ? 0 : (rn() - 0.5) * 2), noseY = 820 + rise
    drawFlame(paint, hx, noseY + 306 * s, s, hit ? 1.25 + rn() * 0.2 : 0, t)
    drawRocket(paint, hx, noseY, s)
    // cel shadow down the right side of the rocket
    x.save(); x.fillStyle = 'rgba(44,26,96,.3)'; x.beginPath(); x.moveTo(hx + 20, noseY + 12); x.bezierCurveTo(hx + 100, noseY + 60, hx + 120, noseY + 280, hx + 70, noseY + 420); x.lineTo(hx + 30, noseY + 420); x.quadraticCurveTo(hx + 70, noseY + 200, hx + 20, noseY + 12); x.fill(); x.restore()
    // the kick: Claude hops up, pulls a leg back, slams it into the rocket
    const hopUp = hit ? 0 : ss(0, kick * 0.8, f2) * 130
    const legBack = hit ? lerp(-78, 0, easeOut(a / 0.08)) : -78 * ss(kick * 0.1, kick * 0.85, f2)
    drawClaude(paint, hx - 6, noseY + 12 - hopUp, 1.3, { armL: hit ? -168 : -150 - windUp * 18, armR: hit ? -12 : -30 + windUp * 10, legL: hit ? 4 : 14, legR: legBack, lean: hit ? 0 : -windUp * 7, headTilt: 0 })
    // impact star + shock ring on the hit
    if (hit && a < 0.42) {
      const k = easeOut(a / 0.3)
      x.strokeStyle = '#fff'; x.lineWidth = 26 * (1 - k) + 2; x.beginPath(); x.ellipse(hx, noseY + 36, 80 + k * 560, 20 + k * 170, 0, 0, 7); x.stroke()
    }
    x.restore()
    // impact frame: 2 inverted frames, the classic anime hit
    if (hit && a < 2 / 30) { x.save(); x.globalCompositeOperation = 'difference'; x.fillStyle = '#fff'; x.fillRect(0, 0, W, H); x.restore() }
    // sparkles
    if (hit) { const sp = rng(9); for (let i = 0; i < 24; i++) { const px = sp() * W, py = sp() * H * 0.55, on = Math.sin(t * 16 + i * 2) > 0.1, k = 12 + sp() * 30; if (!on) continue; x.fillStyle = '#fff'; x.beginPath(); x.moveTo(px - k, py); x.quadraticCurveTo(px, py, px, py - k); x.quadraticCurveTo(px, py, px + k, py); x.quadraticCurveTo(px, py, px, py + k); x.quadraticCurveTo(px, py, px - k, py); x.fill() } }
    // letterbox-free film feel: grain + warm wash
    x.fillStyle = 'rgba(255,190,130,.05)'; x.fillRect(0, 0, W, H)
    x.save(); x.translate(Math.floor(t * 24) * 37 % 256, Math.floor(t * 24) * 91 % 256); x.fillStyle = x.createPattern(this.grain, 'repeat'); x.fillRect(-256, -256, W + 512, H + 512); x.restore()
  },
}
