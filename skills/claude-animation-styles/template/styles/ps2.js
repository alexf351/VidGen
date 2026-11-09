// 02 PS2 STYLE. Few polygons, small muddy textures, fog, drawn at 300x536 and stretched. A game HUD on top.
import * as THREE from 'three'
import { makeClaude, makeRocket, makeFlame } from '../lib/three-claude.js'
import { canvas, clamp, ss, rng, easeOut } from '../lib/common.js'
const RH = 536
const tex = (w, h, draw, rep) => { const c = canvas(w, h); draw(c.getContext('2d'), w, h); const t = new THREE.CanvasTexture(c); t.magFilter = t.minFilter = THREE.NearestFilter; t.colorSpace = THREE.SRGBColorSpace; if (rep) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(rep, rep) } return t }
const noisy = (base, spread, seed) => (x, w, h) => { const r = rng(seed); const [a, b, c] = base; for (let i = 0; i < w; i++) for (let k = 0; k < h; k++) { const v = (r() - 0.5) * spread; x.fillStyle = `rgb(${a + v},${b + v},${c + v * 0.7})`; x.fillRect(i, k, 1, 1) } }
export default {
  name: 'ps2 style',
  hero: 0.74,
  create({ W, H, renderer }) {
    this.W = W; this.H = H; this.r = renderer; const RW = (this.RW = Math.round((W / H) * RH))
    const s = (this.scene = new THREE.Scene())
    s.fog = new THREE.Fog(0x8a6f8c, 26, 70)
    // dusk sky on a big sphere
    const sky = tex(8, 128, (x, w, h) => { const g = x.createLinearGradient(0, 0, 0, h); g.addColorStop(0, '#20285c'); g.addColorStop(0.42, '#5a4a86'); g.addColorStop(0.62, '#c4708a'); g.addColorStop(0.74, '#f3a56b'); g.addColorStop(1, '#f3a56b'); x.fillStyle = g; x.fillRect(0, 0, w, h) })
    sky.magFilter = THREE.LinearFilter
    s.add(new THREE.Mesh(new THREE.SphereGeometry(95, 12, 8), new THREE.MeshBasicMaterial({ map: sky, side: THREE.BackSide, fog: false })))
    const moon = new THREE.Mesh(new THREE.CircleGeometry(3.4, 14), new THREE.MeshBasicMaterial({ color: 0xf6f2cf, fog: false })); moon.position.set(12, 21, -46); s.add(moon)
    s.add(new THREE.HemisphereLight(0xc7b6e8, 0x4f4a38, 2.0))
    const sun = new THREE.DirectionalLight(0xffc69a, 2.6); sun.position.set(-8, 12, 10); s.add(sun)
    const lam = (c, map) => new THREE.MeshLambertMaterial({ color: map ? 0xffffff : c, map })
    // ground, house, fence, trees
    const grass = new THREE.Mesh(new THREE.PlaneGeometry(160, 160, 1, 1), lam(0, tex(32, 32, noisy([74, 128, 62], 40, 3), 22))); grass.rotation.x = -Math.PI / 2; s.add(grass)
    const pad = new THREE.Mesh(new THREE.CylinderGeometry(2.4, 2.8, 0.34, 8), lam(0, tex(16, 16, noisy([118, 112, 108], 26, 5)))); pad.position.y = 0.17; s.add(pad)
    const wall = lam(0, tex(32, 32, (x, w, h) => { noisy([192, 170, 136], 24, 8)(x, w, h); x.fillStyle = 'rgba(70,50,30,.5)'; for (let i = 0; i < h; i += 5) x.fillRect(0, i, w, 1) }, 1))
    const house = new THREE.Mesh(new THREE.BoxGeometry(11, 6, 8), wall); house.position.set(-11, 3, -14); s.add(house)
    const roof = new THREE.Mesh(new THREE.ConeGeometry(8.6, 3.6, 4), lam(0, tex(16, 16, noisy([128, 60, 56], 34, 9)))); roof.rotation.y = Math.PI / 4; roof.position.set(-11, 7.8, -14); roof.scale.z = 0.8; s.add(roof)
    const win = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial({ color: 0xffd86a })); win.position.set(-8, 3.4, -9.95); s.add(win)
    const fw = lam(0, tex(16, 16, noisy([128, 96, 68], 30, 12)))
    for (let i = -56; i < 56; i += 1.5) { const p = new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.9, 0.14), fw); p.position.set(i, 0.95, -18); s.add(p) }
    const leaves = lam(0, tex(16, 16, noisy([44, 96, 54], 44, 13)))
    for (const [x, z, k] of [[13, -22, 1.5], [21, -26, 1.9], [-22, -27, 1.7], [9, -33, 2.2], [27, -16, 1.2], [-32, -24, 1.8], [36, -28, 2], [-42, -30, 2.2], [46, -22, 1.5], [-14, -36, 2]]) {
      const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.3 * k, 0.42 * k, 2.6 * k, 5), lam(0x5d4530)); tr.position.set(x, 1.3 * k, z); s.add(tr)
      for (let j = 0; j < 3; j++) { const c = new THREE.Mesh(new THREE.ConeGeometry((2.5 - j * 0.6) * k, 2.8 * k, 6), leaves); c.position.set(x, (3.4 + j * 1.5) * k, z); s.add(c) }
    }
    // the homemade launch tower
    const metal = lam(0, tex(16, 16, noisy([96, 98, 110], 26, 15)))
    const bar = (a, b, c, d, e, f) => { const m = new THREE.Mesh(new THREE.BoxGeometry(a, b, c), metal); m.position.set(d, e, f); s.add(m) }
    bar(0.24, 7, 0.24, -3.3, 3.5, -1); bar(0.24, 7, 0.24, -3.3, 3.5, 1); bar(0.24, 7, 0.24, -5.2, 3.5, -1); bar(0.24, 7, 0.24, -5.2, 3.5, 1)
    for (let y = 1.2; y < 7.2; y += 1.5) { bar(2.1, 0.14, 0.14, -4.25, y, 1); bar(2.1, 0.14, 0.14, -4.25, y, -1) }
    bar(2.5, 0.2, 2.4, -4.25, 7, 0)
    // cast
    const kit = { seg: 6, smooth: false, mat: (c) => new THREE.MeshLambertMaterial({ color: c }) }
    this.rocket = makeRocket({ ...kit, seg: 8 }); this.rocket.position.y = 0.34; s.add(this.rocket)
    this.claude = makeClaude(kit); s.add(this.claude)
    this.flame = makeFlame({ seg: 6 }); this.flame.position.y = 0.3; this.flame.scale.setScalar(0); s.add(this.flame)
    const blob = new THREE.Mesh(new THREE.CircleGeometry(0.9, 10), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.38 })); blob.rotation.x = -Math.PI / 2; blob.position.y = 0.04; this.blob = blob; s.add(blob)
    this.cam = new THREE.PerspectiveCamera(50, RW / RH, 0.1, 200)
    this.low = canvas(RW, RH)
    this.lines = canvas(4, 4); const lx = this.lines.getContext('2d'); lx.fillStyle = 'rgba(0,0,0,.11)'; lx.fillRect(0, 0, 4, 2)
  },
  render(t, ctx, dur) {
    const c = this.claude, ud = c.userData
    // walks onto the tower deck, hops across to the nose, throws its arms up
    const hop0 = dur * 0.34, hop1 = dur * 0.58, u = clamp((t - hop0) / (hop1 - hop0))
    const deck = [-4.25, 7.1, 0], nose = [0, 3.34, 0]
    const walk = 1 - easeOut(t / hop0)
    c.position.set(deck[0] - walk * 0.8 + (nose[0] - deck[0]) * u, deck[1] + (nose[1] - deck[1]) * u + Math.sin(u * Math.PI) * 2.1, 0)
    const stride = u === 0 ? Math.sin(t * 16) * 26 : 0
    if (u <= 0) ud.pose({ al: 18 - stride, ar: -18 + stride, ll: stride, lr: -stride, tilt: Math.sin(t * 16) * 3 })
    else if (u < 1) ud.pose({ al: 125, ar: -125, ll: 38, lr: -38 })
    else { const a = Math.sin((t - hop1) * 9) * 12; ud.pose({ al: 122 + a, ar: -122 - a, ll: 6, lr: -6, tilt: a * 0.4 }) }
    c.rotation.y = u <= 0 ? 0.5 : 0.2
    this.blob.position.x = c.position.x * 0.2
    const lit = ss(dur * 0.82, dur, t); this.flame.scale.setScalar(lit * 0.6 * (1 + 0.14 * Math.sin(t * 70)))
    // a game camera: swings round from the tower to the hero angle
    const k = ss(0, dur * 0.72, t), ang = -0.75 + k * 0.92
    const R = 15.5 - k * 4.6
    this.cam.position.set(Math.sin(ang) * R, 4.2 + k * 0.1, Math.cos(ang) * R)
    this.cam.lookAt(-2.2 * (1 - k), 6.9 - k * 1.4, 0)
    // draw small, stretch it
    const RW = this.RW, rr = this.r; rr.shadowMap.enabled = false
    rr.setSize(RW, RH, false); rr.setClearColor(0x000000); rr.render(this.scene, this.cam)
    const lx = this.low.getContext('2d'); lx.drawImage(rr.domElement, 0, 0)
    ctx.imageSmoothingEnabled = true; ctx.drawImage(this.low, 0, 0, this.W, this.H)
    ctx.fillStyle = ctx.createPattern(this.lines, 'repeat'); ctx.fillRect(0, 0, this.W, this.H)
    // HUD
    ctx.textAlign = 'left'; ctx.lineJoin = 'round'
    const hud = (s, x, y, size, col, stroke = 9, align = 'left') => { ctx.textAlign = align; ctx.font = `italic 800 ${size}px "Inter Tight",Arial,sans-serif`; ctx.strokeStyle = '#141018'; ctx.lineWidth = stroke; ctx.strokeText(s, x, y); ctx.fillStyle = col; ctx.fillText(s, x, y) }
    hud('NEW MISSION', 44, 92, 36, '#ffffff', 8)
    hud('REACH THE MOON', 44, 150, 56, '#ffd23f', 11)
    // objective marker and fuel bar
    ctx.fillStyle = '#141018'; ctx.fillRect(44, this.H - 118, 372, 42); ctx.fillStyle = '#343044'; ctx.fillRect(50, this.H - 112, 360, 30)
    ctx.fillStyle = '#58d36a'; ctx.fillRect(50, this.H - 112, 360 * ss(0, dur * 0.9, t), 30)
    hud('FUEL', 44, this.H - 132, 32, '#ffffff', 7)
    if (t > dur * 0.6 && Math.floor(t * 5) % 2 === 0) hud('PRESS X TO LAUNCH', this.W - 44, this.H - 88, 34, '#ffffff', 8, 'right')
    ctx.textAlign = 'left'
  },
}
