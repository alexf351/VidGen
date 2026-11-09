// 04 LEGO STYLE. Everything is plastic bricks with studs: the city, the sky, the rocket, Claude.
import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { ss, rng } from '../lib/common.js'
const U = 0.8, PLATE = 0.32 // one stud across, one plate tall
export default {
  name: 'lego style',
  hero: 0.55,
  create({ W, H, renderer }) {
    this.W = W; this.H = H; this.r = renderer
    const s = (this.scene = new THREE.Scene()); s.background = new THREE.Color(0x4aa8e8)
    s.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture
    s.environmentIntensity = 0.32
    const hemi = new THREE.HemisphereLight(0xffffff, 0x6a7a90, 0.95); s.add(hemi)
    const sun = new THREE.DirectionalLight(0xfff1d6, 2.1); sun.position.set(-14, 26, 22); sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, { left: -40, right: 40, top: 40, bottom: -30, far: 120 }); sun.shadow.bias = -0.0006; s.add(sun); s.add(sun.target); this.sun = sun
    const mat = {}, M = (c) => (mat[c] ??= new THREE.MeshStandardMaterial({ color: c, roughness: 0.3, metalness: 0 }))
    const boxG = new RoundedBoxGeometry(1, 1, 1, 2, 0.04), studG = new THREE.CylinderGeometry(0.24 * U, 0.24 * U, 0.17, 18)
    const bricks = [], studs = []
    // A brick spans w x d studs and h plates, sitting with its corner at x, y, z. Studs go on top when asked.
    const add = (x, y, z, w, d, h, c, top = true, list = bricks) => {
      list.push({ x: x + (w * U) / 2, y: y + (h * PLATE) / 2, z: z + (d * U) / 2, sx: w * U - 0.02, sy: h * PLATE - 0.015, sz: d * U - 0.02, c })
      if (top) for (let a = 0; a < w; a++) for (let b = 0; b < d; b++) studs.push({ x: x + (a + 0.5) * U, y: y + h * PLATE + 0.08, z: z + (b + 0.5) * U, c })
    }
    // a big studded baseplate as the sky, far back
    const skyC = 0x58b2ec
    for (let a = -36; a < 36; a++) for (let b = -12; b < 62; b++) { studs.push({ x: a * U * 1.6, y: b * U * 1.6, z: -22.4, c: skyC, face: true }) }
    const back = new THREE.Mesh(new THREE.PlaneGeometry(130, 140), M(skyC)); back.position.set(0, 46, -22.5); s.add(back)
    // skyscrapers. Each wall is staggered bricks with window rows.
    const r = rng(21), palette = [0xd8432f, 0xf2c230, 0xe9e4d6, 0x2f6fc4, 0x3aa35c, 0xef8a3a]
    const tower = (x0, z0, wide, floors, c) => {
      for (let f = 0; f < floors; f++) {
        const y = f * PLATE * 3, window = f % 3 === 1
        let xx = x0, off = f % 2 ? 1 : 0
        if (off) { add(xx, y, z0, 1, 1, 3, c, false); xx += U }
        while (xx < x0 + wide * U - 0.01) {
          const left = Math.round((x0 + wide * U - xx) / U), w = Math.min(left, 2)
          if (window && w === 2) { add(xx, y, z0, 1, 1, 3, c, false); add(xx + U, y, z0, 1, 1, 3, 0x173a5e, false) }
          else add(xx, y, z0, w, 1, 3, c, false)
          xx += w * U
        }
      }
      add(x0, floors * PLATE * 3, z0, wide, 1, 1, c, true)
    }
    tower(-12.4, -5, 8, 17, palette[0]); tower(5.6, -6, 8, 24, palette[1]); tower(-16, -11, 9, 30, palette[3]); tower(8, -11, 9, 20, palette[2])
    tower(-3.4, -15, 8, 14, palette[4]); tower(-25, -9, 9, 26, palette[2]); tower(15.5, -9, 9, 28, palette[0]); tower(-21, 2.8, 5, 13, palette[4]); tower(13, 2.6, 5, 11, palette[5]); tower(24, -11, 8, 18, palette[3]); tower(-33, -11, 8, 16, palette[5]); tower(-9.6, 3.4, 4, 9, palette[5]); tower(6.8, 3, 4, 7, palette[3])
    // white brick clouds up top
    const cloud = (x, y, z, w) => { add(x + U * 2, y + PLATE * 2, z, w - 4, 2, 2, 0xffffff); add(x + U, y + PLATE, z, w - 2, 2, 1, 0xffffff, false); add(x, y, z, w, 2, 1, 0xffffff, false) }
    cloud(-9, 18, -3, 9); cloud(3.6, 24, -8, 11); cloud(-13, 29, -7, 12); cloud(4.6, 35, -3, 8); cloud(-9, 41, -4, 10); cloud(-1, 15, -14, 12); cloud(13, 22, -4, 10); cloud(-20, 25, -5, 11); cloud(14, 31, -6, 12); cloud(-21, 37, -4, 9)
    // instance everything by colour
    const put = (list, geo) => {
      const by = new Map(); list.forEach((b) => { if (!by.has(b.c)) by.set(b.c, []); by.get(b.c).push(b) })
      const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), qf = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2)
      for (const [c, arr] of by) {
        const im = new THREE.InstancedMesh(geo, M(c), arr.length); im.castShadow = true; im.receiveShadow = true
        arr.forEach((b, i) => { m4.compose(new THREE.Vector3(b.x, b.y, b.z), b.face ? qf : q, new THREE.Vector3(b.sx ?? 1, b.sy ?? 1, b.sz ?? 1)); im.setMatrixAt(i, m4) })
        s.add(im)
      }
    }
    put(bricks, boxG); put(studs, studG)

    // the rocket + Claude, as one little model that moves together
    const hero = (this.hero3 = new THREE.Group()); s.add(hero)
    const hb = [], hs = []
    const addH = (x, y, z, w, d, h, c, top = false) => {
      hb.push({ x: x * U, y: (y + h / 2) * PLATE, z: z * U, sx: w * U - 0.02, sy: h * PLATE - 0.015, sz: d * U - 0.02, c })
      if (top) for (let a = 0; a < w; a++) for (let b = 0; b < d; b++) hs.push({ x: (x - w / 2 + a + 0.5) * U, y: (y + h) * PLATE + 0.08, z: (z - d / 2 + b + 0.5) * U, c })
    }
    const WH = 0xf4f1ea, RED = 0xd8432f, GL = 0x56b6ee
    addH(0, 0, 0, 2, 2, 2, 0x4a4a50)
    for (let i = 0; i < 12; i++) {
      const stripe = i === 0 || i === 1
      addH(0, 2 + i * 1, 0, 4, 4, 1, stripe ? RED : WH, i === 11 ? false : false)
    }
    addH(0, 7, 2.05, 2, 0.1, 3, GL); addH(0, 14, 0, 4, 4, 2, RED); addH(0, 16, 0, 2, 2, 2, RED, true)
    // fins
    addH(-2.7, 2, 0, 1.4, 2, 4, RED); addH(2.7, 2, 0, 1.4, 2, 4, RED); addH(-3.3, 0, 0, 1, 2, 3, RED); addH(3.3, 0, 0, 1, 2, 3, RED)
    // Claude on top: legs, torso, arms
    const topY = 18
    addH(-0.55, topY, 0, 1, 1.2, 5, 0x2f4258); addH(0.55, topY, 0, 1, 1.2, 5, 0x2f4258)
    addH(-0.55, topY, 0.2, 1.1, 1.8, 1, 0xf2efe8); addH(0.55, topY, 0.2, 1.1, 1.8, 1, 0xf2efe8)
    addH(0, topY + 5, 0, 2.4, 1.4, 5, 0x3a3a3e)
    const put2 = (list, geo, parent) => {
      const by = new Map(); list.forEach((b) => { if (!by.has(b.c)) by.set(b.c, []); by.get(b.c).push(b) })
      const m4 = new THREE.Matrix4(), q = new THREE.Quaternion()
      for (const [c, arr] of by) { const im = new THREE.InstancedMesh(geo, M(c), arr.length); im.castShadow = true; im.receiveShadow = true; arr.forEach((b, i) => { m4.compose(new THREE.Vector3(b.x, b.y, b.z), q, new THREE.Vector3(b.sx ?? 1, b.sy ?? 1, b.sz ?? 1)); im.setMatrixAt(i, m4) }); parent.add(im) }
    }
    put2(hb, boxG, hero); put2(hs, studG, hero)
    const armG = new THREE.CylinderGeometry(0.2, 0.2, 1.5, 16), handG = new THREE.CylinderGeometry(0.24, 0.24, 0.26, 16)
    this.arms = [-1, 1].map((sd) => {
      const j = new THREE.Group(); j.position.set(sd * 1.14, (topY + 9) * PLATE, 0); const a = new THREE.Mesh(armG, M(0x3a3a3e)); a.position.y = 0.72; a.castShadow = true; j.add(a)
      const h = new THREE.Mesh(handG, M(0xd85326)); h.position.y = 1.56; h.castShadow = true; j.add(h); hero.add(j); j.rotation.z = -sd * 0.6; return j
    })
    // the starburst, made of 8 long bricks round a hub
    const head = (this.head = new THREE.Group()); head.position.set(0, (topY + 10) * PLATE + 1.05, 0.05); hero.add(head)
    const rayG = new RoundedBoxGeometry(0.46, 1.34, 0.46, 3, 0.07)
    for (let i = 0; i < 8; i++) { const a = (i * Math.PI) / 4; const m = new THREE.Mesh(rayG, M(0xd85326)); m.position.set(Math.sin(a) * 0.78, Math.cos(a) * 0.78, 0); m.rotation.z = -a; m.castShadow = true; head.add(m); const st = new THREE.Mesh(studG, M(0xd85326)); st.rotation.x = Math.PI / 2; st.position.set(Math.sin(a) * 0.92, Math.cos(a) * 0.92, 0.27); head.add(st) }
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.46, 0.46, 0.5, 8), M(0xd85326)); hub.rotation.x = Math.PI / 2; head.add(hub)
    // transparent plastic flame bricks
    this.flames = []
    const flameM = (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.2, transparent: true, opacity: 0.86 })
    for (let i = 0; i < 16; i++) {
      const m = new THREE.Mesh(boxG, flameM(i < 6 ? 0xffe36b : i < 11 ? 0xf79a2e : 0xe8552a)); const k = i < 6 ? 1.1 : i < 11 ? 1.5 : 1.8
      m.scale.set(0.55 * k, 0.34, 0.55 * k); hero.add(m); this.flames.push(m)
    }
    this.cam = new THREE.PerspectiveCamera(30, W / H, 0.1, 200)
  },
  render(t, ctx, dur) {
    const u = t / dur, climb = ss(0, 1, u) * 0.35 + u * 0.65
    const y = 3 + climb * 25
    const wob = Math.sin(t * 3.1) * 0.12
    const h = this.hero3; h.position.set(wob, y, 1); h.rotation.z = Math.sin(t * 2.3) * 0.03; h.rotation.y = -0.34 + Math.sin(t * 1.3) * 0.05
    this.arms[0].rotation.z = 0.62 + Math.sin(t * 13) * 0.14; this.arms[1].rotation.z = -0.62 - Math.sin(t * 13) * 0.14
    this.flames.forEach((m, i) => {
      const ph = (t * 7 + i * 0.37) % 1, spread = 0.2 + ph * 0.7, a = i * 2.4
      m.position.set(Math.cos(a) * spread, -0.2 - ph * 2.8 - (i % 3) * 0.24, Math.sin(a) * spread * 0.7); m.visible = true
    })
    this.cam.position.set(0, y + 5.4, 31); this.cam.lookAt(0, y + 5.0, 0)
    this.sun.position.set(-14, y + 26, 22); this.sun.target.position.set(0, y + 2, 0); this.sun.target.updateMatrixWorld()
    const rr = this.r; rr.shadowMap.enabled = true; rr.shadowMap.needsUpdate = true
    rr.toneMapping = THREE.ACESFilmicToneMapping; rr.toneMappingExposure = 1.02
    rr.setSize(this.W, this.H, false); rr.render(this.scene, this.cam)
    rr.toneMapping = THREE.NoToneMapping
    ctx.drawImage(rr.domElement, 0, 0, this.W, this.H)
  },
}
