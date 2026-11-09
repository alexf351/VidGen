export const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v))
export const lerp = (a, b, u) => a + (b - a) * u
export const ss = (a, b, v) => { const u = clamp((v - a) / (b - a)); return u * u * (3 - 2 * u) }
export const easeOut = (u) => 1 - Math.pow(1 - clamp(u), 3)
export const easeIn = (u) => Math.pow(clamp(u), 3)
export const backOut = (u, k = 1.70158) => { const v = clamp(u) - 1; return v * v * ((k + 1) * v + k) + 1 }
export const rng = (seed) => { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296 } }
export const canvas = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c }

// The Claude character in 2D, built from pieces, so each style can paint the pieces its own way.
// paint.fill(path, key), paint.lines(segments, width, key). x, y = between the feet. s = scale (1 = 200px tall body + head).
export function drawClaude(paint, x, y, s, pose = {}) {
  const { armL = -155, armR = -25, legL = 8, legR = -8, lean = 0, headTilt = 0, spin = 0 } = pose
  const r = (d) => (d * Math.PI) / 180
  const P = (dx, dy) => { const c = Math.cos(r(lean)), n = Math.sin(r(lean)); return [x + (dx * c - dy * n) * s, y + (dx * n + dy * c) * s] }
  const hipY = -70, shoulderY = -158, neckY = -176
  // legs and sneakers
  const leg = (hx, a) => { const [a0, b0] = P(hx, hipY); const ang = r(a + 90 + lean); const L = 66 * s; return [a0, b0, a0 + Math.cos(ang) * L, b0 + Math.sin(ang) * L] }
  const ll = leg(-17, legL), lr = leg(17, legR)
  paint.lines([ll, lr], 30 * s, 'jeans')
  const shoe = (l, dir) => { const pp = new Path2D(); pp.ellipse(l[2] + dir * 9 * s, l[3] + 4 * s, 23 * s, 13 * s, 0, 0, Math.PI * 2); return pp }
  paint.fill(shoe(ll, -1), 'shoe'); paint.fill(shoe(lr, 1), 'shoe')
  // arms go behind the hoodie
  const arm = (sx, a) => { const [a0, b0] = P(sx, shoulderY + 8); const ang = r(a + lean); const L = 70 * s; return [a0, b0, a0 + Math.cos(ang) * L, b0 + Math.sin(ang) * L] }
  const al = arm(-40, armL), ar = arm(40, armR)
  paint.lines([al, ar], 28 * s, 'hood')
  const hand = (l) => { const pp = new Path2D(); pp.arc(l[2], l[3], 15 * s, 0, Math.PI * 2); return pp }
  paint.fill(hand(al), 'star'); paint.fill(hand(ar), 'star')
  // hoodie
  const body = new Path2D()
  const [bx, by] = P(0, hipY + 12)
  const w = 94 * s, h = 110 * s
  const c = Math.cos(r(lean)), n = Math.sin(r(lean))
  const pts = [[-w / 2, 0], [w / 2, 0], [w / 2 * 0.98, -h * 0.9], [w * 0.3, -h], [-w * 0.3, -h], [-w / 2 * 0.98, -h * 0.9]].map(([a, b]) => [bx + a * c - b * n, by + a * n + b * c])
  body.moveTo((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
  for (let i = 1; i <= pts.length; i++) { const p = pts[i % pts.length], q = pts[(i + 1) % pts.length]; body.arcTo(p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2, 15 * s) }
  body.closePath()
  paint.fill(body, 'hood')
  // pocket + drawstrings
  const [px, py] = P(0, hipY - 6)
  const pocket = new Path2D(); pocket.roundRect(px - 28 * s, py - 28 * s, 56 * s, 30 * s, 8 * s)
  paint.fill(pocket, 'hoodDark')
  // the head: the starburst
  const [hx, hy] = P(0, neckY - 42)
  const R = 88 * s, segs = []
  for (let i = 0; i < 8; i++) { const a = r(i * 45 + headTilt + spin); segs.push([hx, hy, hx + Math.cos(a) * R, hy + Math.sin(a) * R]) }
  paint.lines(segs, 31 * s, 'star')
  return { hand: [ar[2], ar[3]], handL: [al[2], al[3]], head: [hx, hy] }
}

// The rocket. x, y = its nose tip, where Claude stands. s = scale. Returns where the flame starts.
export function drawRocket(paint, x, y, s, { tilt = 0 } = {}) {
  const r = (tilt * Math.PI) / 180, c = Math.cos(r), n = Math.sin(r)
  const P = (a, b) => [x + (a * c - b * n) * s, y + (a * n + b * c) * s]
  const path = (cmd) => { const p = new Path2D(); cmd(p); return p }
  const W = 76
  // fins
  paint.fill(path((p) => { p.moveTo(...P(-W + 8, 190)); p.quadraticCurveTo(...P(-W - 52, 230), ...P(-W - 50, 310)); p.lineTo(...P(-W + 20, 262)); p.closePath() }), 'fin')
  paint.fill(path((p) => { p.moveTo(...P(W - 8, 190)); p.quadraticCurveTo(...P(W + 52, 230), ...P(W + 50, 310)); p.lineTo(...P(W - 20, 262)); p.closePath() }), 'fin')
  // nozzle
  paint.fill(path((p) => { p.moveTo(...P(-30, 276)); p.lineTo(...P(30, 276)); p.lineTo(...P(42, 306)); p.lineTo(...P(-42, 306)); p.closePath() }), 'nozzle')
  // body
  paint.fill(path((p) => { p.moveTo(...P(0, 0)); p.bezierCurveTo(...P(W * 1.0, 40), ...P(W * 1.05, 190), ...P(W * 0.62, 284)); p.lineTo(...P(-W * 0.62, 284)); p.bezierCurveTo(...P(-W * 1.05, 190), ...P(-W * 1.0, 40), ...P(0, 0)); p.closePath() }), 'body')
  // nose
  paint.fill(path((p) => { p.moveTo(...P(0, 0)); p.bezierCurveTo(...P(W * 0.62, 26), ...P(W * 0.82, 62), ...P(W * 0.9, 92)); p.quadraticCurveTo(...P(0, 112), ...P(-W * 0.9, 92)); p.bezierCurveTo(...P(-W * 0.82, 62), ...P(-W * 0.62, 26), ...P(0, 0)); p.closePath() }), 'nose')
  // window
  const [wx, wy] = P(0, 162)
  paint.fill(path((p) => p.arc(wx, wy, 36 * s, 0, Math.PI * 2)), 'rim')
  paint.fill(path((p) => p.arc(wx, wy, 24 * s, 0, Math.PI * 2)), 'window')
  return { tail: P(0, 306), angle: r }
}

// Flame under the rocket. grow = 0..1.3, t = time for the flicker.
export function drawFlame(paint, x, y, s, grow, t, tilt = 0) {
  if (grow <= 0.02) return
  const r = (tilt * Math.PI) / 180, c = Math.cos(r), n = Math.sin(r)
  const f = 1 + 0.12 * Math.sin(t * 47) + 0.08 * Math.sin(t * 91)
  const shape = (w, L, key) => {
    const P = (a, b) => [x + (a * c - b * n) * s, y + (a * n + b * c) * s]
    const p = new Path2D(); const l = L * grow * f, ww = w * Math.min(1, grow)
    p.moveTo(...P(-ww, 0)); p.quadraticCurveTo(...P(-ww * 1.1, l * 0.42), ...P(0, l)); p.quadraticCurveTo(...P(ww * 1.1, l * 0.42), ...P(ww, 0)); p.closePath()
    paint.fill(p, key)
  }
  shape(40, 220, 'flame1'); shape(26, 150, 'flame2'); shape(13, 80, 'flame3')
}
