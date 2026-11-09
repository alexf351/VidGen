// 01 PIXEL ART. Drawn at 120x214 real pixels with a small palette, then scaled up with no smoothing.
import { canvas, clamp, ss, rng } from '../lib/common.js'
const PH = 214
const NAVY = ['#10123a', '#171a4d', '#1f2460', '#2a3074', '#3a3f8a']
// A bitmap font with every capital, digit and common mark. Text in this style only ever comes from here.
const GLYPHS = { A:'010,101,111,101,101', B:'110,101,110,101,110', C:'011,100,100,100,011', D:'110,101,101,101,110', E:'111,100,110,100,111', F:'111,100,110,100,100', G:'011,100,101,101,011', H:'101,101,111,101,101', I:'111,010,010,010,111', J:'001,001,001,101,010', K:'101,101,110,101,101', L:'100,100,100,100,111', M:'10001,11011,10101,10001,10001', N:'1001,1101,1011,1001,1001', O:'111,101,101,101,111', P:'110,101,110,100,100', Q:'010,101,101,110,011', R:'110,101,110,101,101', S:'011,100,010,001,110', T:'111,010,010,010,010', U:'101,101,101,101,111', V:'101,101,101,101,010', W:'10001,10001,10101,11011,10001', X:'101,101,010,101,101', Y:'101,101,010,010,010', Z:'111,001,010,100,111', '0':'111,101,101,101,111', '1':'010,110,010,010,111', '2':'111,001,111,100,111', '3':'111,001,111,001,111', '4':'101,101,111,001,001', '5':'111,100,111,001,111', '6':'111,100,111,101,111', '7':'111,001,010,010,010', '8':'111,101,111,101,111', '9':'111,101,111,001,111', ' ':'000,000,000,000,000', ',':'000,000,000,010,100', '.':'000,000,000,000,010', '!':'010,010,010,000,010', '?':'110,001,010,000,010', ':':'000,010,000,010,000', '-':'000,000,111,000,000', "'":'010,010,000,000,000', '$':'011,110,010,011,110', '%':'101,001,010,100,101' }
export default {
  name: 'pixel art',
  hero: 0.72,
  create({ W, H }) { this.W = W; this.H = H; this.PW = Math.round((W / H) * PH); this.c = canvas(this.PW, PH); this.x = this.c.getContext('2d') },
  render(t, ctx, dur) {
    const PW = this.PW, x = this.x, px = (a, b, w = 1, h = 1) => x.fillRect(Math.round(a), Math.round(b), w, h)
    const up = Math.round(ss(0, dur * 0.8, t) * 18) // the camera tilts up to the moon
    // night sky in flat bands, dithered where they meet
    const bands = [0, 38, 80, 124, 170]
    bands.forEach((b, i) => { x.fillStyle = NAVY[i]; px(0, b + up, PW, 60) })
    x.fillStyle = NAVY[0]; px(0, 0, PW, up + 1)
    bands.slice(1).forEach((b, i) => { x.fillStyle = NAVY[i]; for (let a = 0; a < PW; a += 2) for (let k = 0; k < 4; k += 2) px(a + (k ? 1 : 0), b + up + k, 1, 1) })
    // stars
    const r = rng(7)
    for (let i = 0; i < PW * 0.4; i++) {
      const a = r() * PW, b = r() * 150, ph = r() * 6.28, on = Math.sin(t * 5 + ph) > -0.3
      x.fillStyle = on ? (i % 5 ? '#c9cdf2' : '#ffffff') : '#4a4f9a'; px(a, b + up * 0.5, 1, 1)
      if (i % 11 === 0 && Math.sin(t * 4 + ph) > 0.5) { x.fillStyle = '#ffffff'; px(a - 1, b + up * 0.5); px(a + 1, b + up * 0.5); px(a, b + up * 0.5 - 1); px(a, b + up * 0.5 + 1) }
    }
    // the moon
    const mx = PW * 0.71, my = 44 + up * 0.5, mr = PW > 200 ? 24 : 21
    for (let a = -mr; a <= mr; a++) for (let b = -mr; b <= mr; b++) {
      const d = Math.hypot(a, b); if (d > mr) continue
      x.fillStyle = d > mr - 1.4 ? '#c9c7a8' : (a + b > 16 ? '#dcdab8' : '#f3f1cf'); px(mx + a, my + b)
    }
    x.fillStyle = '#cfcdab'
    for (const [a, b, s] of [[-7, -6, 4], [6, -11, 2], [8, 4, 3], [-3, 9, 3], [-13, 3, 2]]) for (let i = -s; i <= s; i++) for (let k = -s; k <= s; k++) if (Math.hypot(i, k) <= s) px(mx + a + i, my + b + k)
    // a shooting star crosses at the start
    const sh = (t - 0.2) * 95
    if (sh > 0 && sh < PW + 6) { x.fillStyle = '#ffffff'; px(sh, 22 + sh * 0.2); x.fillStyle = '#8f93d8'; for (let k = 1; k < 7; k++) px(sh - k, 22 + (sh - k) * 0.2) }
    // far hills + house
    const ground = 172 + up
    x.fillStyle = '#16244a'
    for (let a = 0; a < PW; a++) px(a, ground - 12 - Math.round(4 * Math.sin(a * 0.09) + 3 * Math.sin(a * 0.21)), 1, 16)
    // house
    const hx = Math.max(7, Math.round(PW / 2 - 63)), hy = ground - 33
    x.fillStyle = '#3a2c52'; px(hx, hy + 9, 30, 25)
    x.fillStyle = '#7d3a4d'; for (let k = 0; k < 10; k++) px(hx - 3 + k, hy + 9 - k, 36 - k * 2, 1)
    x.fillStyle = '#ffd86a'; px(hx + 5, hy + 15, 8, 8); x.fillStyle = '#3a2c52'; px(hx + 8, hy + 15, 2, 8); px(hx + 5, hy + 18, 8, 2)
    x.fillStyle = '#231b36'; px(hx + 19, hy + 20, 7, 14)
    // fence
    x.fillStyle = '#4b4f7f'; for (let a = 0; a < PW; a += 5) if (a < hx - 5 || a > hx + 33) px(a, ground - 8, 3, 9); px(0, ground - 5, hx - 3, 1); px(hx + 33, ground - 5, PW, 1)
    // grass
    x.fillStyle = '#1f6b47'; px(0, ground, PW, 80); x.fillStyle = '#2a8a58'; px(0, ground, PW, 3)
    x.fillStyle = '#1a5a3d'; const g = rng(3); for (let i = 0; i < PW * 0.5; i++) px(g() * PW, ground + 5 + g() * 40, 2, 1)
    x.fillStyle = '#35a36b'; for (let a = 2; a < PW; a += 7) px(a + (a % 3), ground - 1, 1, 1)
    // Claude: starburst head, hoodie, jeans. Standing, then looking up.
    const cx = Math.round(PW / 2), feet = ground + 14, bob = Math.sin(t * 7) > 0 ? 0 : 1
    x.fillStyle = 'rgba(8,30,20,.5)'; px(cx - 8, feet + 1, 16, 2)
    x.fillStyle = '#f2efe8'; px(cx - 7, feet - 2, 6, 2); px(cx + 1, feet - 2, 6, 2)
    x.fillStyle = '#2f4258'; px(cx - 6, feet - 9, 5, 7); px(cx + 1, feet - 9, 5, 7)
    x.fillStyle = '#26262b'; px(cx - 8, feet - 21 + bob, 16, 13 - bob)
    x.fillStyle = '#3a3a3e'; px(cx - 7, feet - 21 + bob, 14, 12 - bob)
    x.fillStyle = '#26262b'; px(cx - 4, feet - 13, 8, 3)
    // arm points up at the moon once it sees it
    const see = t > dur * 0.42
    x.fillStyle = '#3a3a3e'
    if (see) { for (let k = 0; k < 9; k++) px(cx + 7 + k, feet - 18 - k, 3, 3); x.fillStyle = '#d97757'; px(cx + 15, feet - 29, 3, 3) }
    else { px(cx + 7, feet - 20, 3, 9); x.fillStyle = '#d97757'; px(cx + 7, feet - 11, 3, 2) }
    x.fillStyle = '#3a3a3e'; px(cx - 10, feet - 20 + bob, 3, 9); x.fillStyle = '#d97757'; px(cx - 10, feet - 11 + bob, 3, 2)
    // the starburst, with a dark outline, plotted pixel by pixel
    const hy2 = feet - 35 + bob, R = 14, inStar = (a, b) => { const ang = Math.atan2(b, a), d = Math.hypot(a, b), k = (ang / (Math.PI / 4)), near = Math.abs(k - Math.round(k)) * (Math.PI / 4); return d <= R && (d * Math.sin(near) <= 2.3 || d <= 4.6) }
    for (let a = -R - 1; a <= R + 1; a++) for (let b = -R - 1; b <= R + 1; b++) {
      if (inStar(a, b)) { x.fillStyle = a + b > 7 ? '#b95f42' : (a + b < -8 ? '#ee9270' : '#d97757'); px(cx + a, hy2 + b) }
      else if (inStar(a + 1, b) || inStar(a - 1, b) || inStar(a, b + 1) || inStar(a, b - 1)) { x.fillStyle = '#5a2a1c'; px(cx + a, hy2 + b) }
    }
    // the "!" when it spots the moon, then the HUD
    const text = (s, a, b, col) => { x.fillStyle = col; let cur = a; for (const ch of s.toUpperCase()) { const g = (GLYPHS[ch] || GLYPHS[' ']).split(','); g.forEach((row, j) => [...row].forEach((v, i) => { if (v === '1') px(cur + i, b + j) })); cur += g[0].length + 1 } }
    if (t > dur * 0.42 && t < dur * 0.8 && Math.floor(t * 8) % 2 === 0) { x.fillStyle = '#ffd86a'; px(cx - 1, hy2 - 26, 3, 7); px(cx - 1, hy2 - 17, 3, 3) }
    text('LV 01', 5, 6, '#ffffff')
    text('MOON', 5, 13, '#ffd86a')
    text('384,400 KM', 5 + 22, 13, '#ffd86a')
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(this.c, 0, 0, this.W, this.H)
    ctx.imageSmoothingEnabled = true
  },
}
