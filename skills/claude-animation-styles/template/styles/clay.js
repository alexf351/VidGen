// 05 CLAYMATION. Soft shapes with thumbprints in them, soft light, and only 12 poses a second, like stop motion.
import * as THREE from 'three'
import { makeClaude, makeRocket, makeFlame } from '../lib/three-claude.js'
import { canvas, clamp, ss, rng } from '../lib/common.js'
function thumbprints() {
  const c = canvas(512, 512), x = c.getContext('2d'); x.fillStyle = '#808080'; x.fillRect(0, 0, 512, 512)
  const r = rng(5)
  for (let i = 0; i < 90; i++) {
    const a = r() * 512, b = r() * 512, k = 14 + r() * 26, tilt = r() * 6.28
    x.save(); x.translate(a, b); x.rotate(tilt); x.lineWidth = 1.1
    for (let j = 2; j < k; j += 3.2) { x.strokeStyle = `rgba(${r() > 0.5 ? '255,255,255' : '0,0,0'},.13)`; x.beginPath(); x.ellipse(0, 0, j, j * 1.25, 0, 0, Math.PI * 2); x.stroke() }
    x.restore()
  }
  for (let i = 0; i < 26; i++) { const g = x.createRadialGradient(0, 0, 0, 0, 0, 1); x.save(); x.translate(r() * 512, r() * 512); const k = 22 + r() * 40; x.scale(k, k * (0.6 + r() * 0.7)); g.addColorStop(0, 'rgba(0,0,0,.2)'); g.addColorStop(1, 'rgba(0,0,0,0)'); x.fillStyle = g; x.beginPath(); x.arc(0, 0, 1, 0, 6.3); x.fill(); x.restore() }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; return t
}
export default {
  name: 'claymation',
  hero: 0.55,
  create({ W, H, renderer }) {
    this.W = W; this.H = H; this.r = renderer
    const s = (this.scene = new THREE.Scene()); s.background = new THREE.Color(0xbfeaf2)
    s.fog = new THREE.Fog(0xbfeaf2, 34, 74)
    s.add(new THREE.HemisphereLight(0xffffff, 0xb9c9d8, 1.75))
    const key = new THREE.DirectionalLight(0xfff2de, 2.7); key.position.set(-9, 15, 16); key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.radius = 9; key.shadow.blurSamples = 24
    Object.assign(key.shadow.camera, { left: -24, right: 24, top: 20, bottom: -16, far: 70 }); s.add(key); s.add(key.target); this.key = key
    const fill = new THREE.DirectionalLight(0xbcd8ff, 0.7); fill.position.set(10, 4, 8); s.add(fill)
    const bump = (this.bump = thumbprints())
    const mat = (c, rep = 1) => { const b = bump.clone(); b.repeat.set(rep, rep); b.needsUpdate = true; return new THREE.MeshPhysicalMaterial({ color: c, roughness: 0.72, sheen: 0.5, sheenRoughness: 0.7, sheenColor: new THREE.Color(c), bumpMap: b, bumpScale: 3.2 }) }
    this.mats = []
    const K = (c, rep) => { const m = mat(c, rep); this.mats.push(m); return m }
    const kit = { seg: 28, selfShadow: true, mat: (c) => K(c, 1.2), star: 0xd8653c, hood: 0x45454c, jeans: 0x3c5a80, shoe: 0xf6f2ea, body: 0xf4efe4, nose: 0xdd4a33, rim: 0xdd4a33, nozzle: 0x55555c, glass: 0x3f9ad6 }
    // the hero, tilted a touch, with a chunky clay flame
    const hero = (this.hero3 = new THREE.Group()); s.add(hero)
    this.rocket = makeRocket(kit); hero.add(this.rocket)
    this.claude = makeClaude(kit); this.claude.position.y = 2.98; hero.add(this.claude)
    this.flames = []
    const fm = [K(0xf26a2e, 1), K(0xf9b432, 1), K(0xfff0b8, 1)]
    for (let i = 0; i < 3; i++) { const m = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 18), fm[i]); hero.add(m); this.flames.push(m) }
    // clouds: blobs of white clay
    const cloudM = K(0xffffff, 3), r = rng(13), cloudG = new THREE.SphereGeometry(1, 28, 20)
    this.clouds = []
    const cloud = (x, y, z, k) => {
      const g = new THREE.Group()
      const n = 6 + Math.floor(r() * 3)
      for (let i = 0; i < n; i++) { const m = new THREE.Mesh(cloudG, cloudM); const u = i / (n - 1) - 0.5, rad = (1.1 + r() * 0.95) * (1 - Math.abs(u) * 0.8); m.scale.setScalar(rad); m.position.set(u * 6.2, (r() - 0.3) * 1 + rad * 0.4, (r() - 0.5) * 1.6); m.receiveShadow = true; g.add(m) }
      g.position.set(x, y, z); g.scale.setScalar(k); s.add(g); this.clouds.push(g)
    }
    for (let i = 0; i < 24; i++) { const side = i % 2 ? 1 : -1; cloud(side * (3.8 + r() * 6.2), i * 2.9 - 6, -2 - r() * 7 + (i % 5 === 0 ? 7 : 0), 0.65 + r() * 0.65) }
    // a clay sun and birds
    const sun = new THREE.Mesh(new THREE.SphereGeometry(2.4, 32, 24), K(0xf7c83a, 1.5)); sun.position.set(7.2, 15, -11); this.sun = sun; s.add(sun)
    this.birds = []
    const body = K(0x5d7fb0, 1.4), beak = K(0xf0a13a, 1)
    for (let i = 0; i < 4; i++) {
      const g = new THREE.Group(); const b = new THREE.Mesh(new THREE.SphereGeometry(0.42, 20, 16), body); b.scale.set(1.5, 0.92, 0.9); g.add(b)
      const n = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.42, 12), beak); n.rotation.z = -Math.PI / 2; n.position.x = 0.74; g.add(n)
      const w1 = new THREE.Mesh(new THREE.SphereGeometry(0.34, 16, 12), body); w1.scale.set(1.25, 0.26, 1.9); w1.position.set(-0.05, 0.1, 0.58); g.add(w1)
      const w2 = w1.clone(); w2.position.z = -0.58; g.add(w2); g.userData = { w1, w2 }; s.add(g); this.birds.push(g)
    }
    this.cam = new THREE.PerspectiveCamera(30, W / H, 0.1, 150)
    this.grain = canvas(240, 240); const gx = this.grain.getContext('2d'); const gr = rng(2); for (let i = 0; i < 240; i++) for (let k = 0; k < 240; k++) { const v = gr() * 255; gx.fillStyle = `rgba(${v},${v},${v},.05)`; gx.fillRect(i, k, 1, 1) }
  },
  render(t0, ctx, dur) {
    const f = Math.floor(t0 * 12), t = f / 12, r = rng(f * 7 + 3) // stop motion: 12 poses a second, every pose a little different
    const u = t / dur, y = u * 26
    const h = this.hero3
    h.position.set(Math.sin(t * 2.4) * 0.25 + (r() - 0.5) * 0.03, y, 1); h.rotation.z = Math.sin(t * 2.1) * 0.07 + (r() - 0.5) * 0.008; h.rotation.y = -0.3 + (r() - 0.5) * 0.012
    const ud = this.claude.userData, a = Math.sin(t * 8) * 16
    ud.pose({ al: 122 + a, ar: -122 + a, ll: 8, lr: -8, tilt: Math.sin(t * 5) * 6 })
    this.flames[0].position.set(0, -0.8, 0); this.flames[0].scale.set(0.5 + r() * 0.05, 1.15 + r() * 0.16, 0.5)
    this.flames[1].position.set(0, -0.62, 0.3); this.flames[1].scale.set(0.34, 0.74 + r() * 0.12, 0.3)
    this.flames[2].position.set(0, -0.42, 0.52); this.flames[2].scale.set(0.2, 0.44 + r() * 0.08, 0.16)
    this.clouds.forEach((c, i) => { c.position.x += (r() - 0.5) * 0.012; c.rotation.z = (r() - 0.5) * 0.01 })
    this.birds.forEach((b, i) => {
      const dir = i % 2 ? -1 : 1, p = ((t * (0.46 + i * 0.05) + i * 0.27) % 1)
      b.position.set(dir * (9.5 - p * 19), y + [7.2, -0.6, 6.2, 0.4][i], 1.6)
      b.rotation.y = (dir > 0 ? Math.PI : 0) + 0.55 * dir; b.scale.setScalar(0.92)
      const fl = Math.sin(t * 28 + i) * 0.8; b.userData.w1.rotation.x = fl; b.userData.w2.rotation.x = -fl
    })
    // re-press the thumbprints each pose so the surface boils a little
    this.mats.forEach((m, i) => m.bumpMap.offset.set(((f * 13 + i) % 7) * 0.003, ((f * 7 + i) % 5) * 0.003))
    this.cam.position.set(0, y + 2.8, 18.5); this.cam.lookAt(0, y + 2.5, 0)
    this.key.position.set(-9, y + 15, 16); this.key.target.position.set(0, y + 2, 0); this.key.target.updateMatrixWorld()
    const rr = this.r; rr.shadowMap.enabled = true; rr.shadowMap.needsUpdate = true
    rr.toneMapping = THREE.ACESFilmicToneMapping; rr.toneMappingExposure = 0.98
    rr.setSize(this.W, this.H, false); rr.render(this.scene, this.cam)
    rr.toneMapping = THREE.NoToneMapping
    ctx.drawImage(rr.domElement, 0, 0, this.W, this.H)
    ctx.fillStyle = ctx.createPattern(this.grain, 'repeat'); ctx.fillRect(0, 0, this.W, this.H)
  },
}
