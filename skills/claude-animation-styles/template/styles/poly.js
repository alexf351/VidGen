// 08 LOW POLY 3D. Flat faces, hard light, nothing round. Rocks come at the camera and the rocket swerves.
import * as THREE from 'three'
import { makeClaude, makeRocket, makeFlame } from '../lib/three-claude.js'
import { clamp, ss, rng, lerp } from '../lib/common.js'
const flat = (c, extra = {}) => new THREE.MeshStandardMaterial({ color: c, flatShading: true, roughness: 0.85, ...extra })
function rock(r, detail, seed, col) {
  const g = new THREE.IcosahedronGeometry(r, detail), p = g.attributes.position, rn = rng(seed), seen = new Map()
  for (let i = 0; i < p.count; i++) {
    const k = `${p.getX(i).toFixed(3)},${p.getY(i).toFixed(3)},${p.getZ(i).toFixed(3)}`
    if (!seen.has(k)) seen.set(k, 0.78 + rn() * 0.42)
    const v = seen.get(k); p.setXYZ(i, p.getX(i) * v, p.getY(i) * v, p.getZ(i) * v)
  }
  g.computeVertexNormals()
  return new THREE.Mesh(g, flat(col))
}
export default {
  name: 'low poly 3d',
  hero: 0.42,
  create({ W, H, renderer }) {
    this.W = W; this.H = H; this.r = renderer
    const s = (this.scene = new THREE.Scene()); s.background = new THREE.Color(0x151a4a)
    s.add(new THREE.HemisphereLight(0x8fa8ff, 0x2a1848, 1.5))
    const sun = new THREE.DirectionalLight(0xfff0d8, 4.2); sun.position.set(-9, 12, 12); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, { left: -14, right: 14, top: 18, bottom: -14, far: 60 }); s.add(sun)
    const rim = new THREE.DirectionalLight(0xff7ab8, 1.3); rim.position.set(12, -3, -8); s.add(rim)
    // backdrop: flat-shaded gradient triangles
    const bg = new THREE.PlaneGeometry(140, 240, 14, 24), bp = bg.attributes.position, rn = rng(4), col = []
    const nonIdx = bg.toNonIndexed(); const np = nonIdx.attributes.position
    for (let i = 0; i < np.count; i += 3) {
      const y = (np.getY(i) + 120) / 240, shade = rn() * 0.05
      const c = new THREE.Color().lerpColors(new THREE.Color(0x3b2a8c), new THREE.Color(0x0c1038), clamp(y * 1.3)).offsetHSL(0, 0, shade)
      for (let k = 0; k < 3; k++) col.push(c.r, c.g, c.b)
    }
    nonIdx.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const back = new THREE.Mesh(nonIdx, new THREE.MeshBasicMaterial({ vertexColors: true })); back.position.z = -60; s.add(back)
    // faceted stars
    const starG = new THREE.OctahedronGeometry(0.2), starM = new THREE.MeshBasicMaterial({ color: 0xfff7df }), im = new THREE.InstancedMesh(starG, starM, 360), m4 = new THREE.Matrix4(), rs = rng(9)
    for (let i = 0; i < 360; i++) { const k = 0.5 + rs() * 1.5; m4.compose(new THREE.Vector3((rs() - 0.5) * 120, (rs() - 0.5) * 130, -48 + rs() * 12), new THREE.Quaternion(), new THREE.Vector3(k, k, k)); im.setMatrixAt(i, m4) }
    s.add(im)
    // the moon, growing behind
    this.moon = rock(9, 2, 8, 0xd9d6c4); this.moon.position.set(5, 18, -34); this.moon.castShadow = false; s.add(this.moon)
    const planet = rock(5, 1, 12, 0xef7a55); planet.position.set(-12, -13, -42); s.add(planet); this.planet = planet
    const ring = new THREE.Mesh(new THREE.TorusGeometry(8.2, 0.55, 3, 12), flat(0xf6c24a)); ring.rotation.x = 1.25; ring.rotation.y = 0.3; ring.position.copy(planet.position); s.add(ring)
    // rocks
    this.rocks = []
    const colors = [0x8d7b86, 0x9a8a7a, 0x77728e, 0xa68f76]
    const paths = [[-3.3, 1.0, 0.1, 1.9], [3.8, 4.6, 0.26, 1.6], [-4.1, 7.2, 0.42, 1.2], [3.5, 1.8, 0.56, 2.1], [-3.2, 5.8, 0.72, 1.6], [4.2, 7.9, 0.84, 1.2], [-1.0, -1.8, 0.2, 0.8], [1.5, 9.6, 0.5, 0.9], [-7.2, 3.4, 0.3, 1.9], [7.4, 2.2, 0.62, 2.0], [-6.6, 8.2, 0.05, 1.3], [6.6, 8.4, 0.38, 1.1]]
    paths.forEach(([x, y, at, k], i) => { const m = rock(k, 0, i * 3 + 2, colors[i % 4]); m.castShadow = true; m.receiveShadow = true; m.userData = { x, y, at }; s.add(m); this.rocks.push(m) })
    // hero
    const kit = { seg: 6, smooth: false, mat: (c) => flat(c), selfShadow: false, body: 0xf1ede2, nose: 0xe34b34, rim: 0xe34b34, glass: 0x6fd1f5, star: 0xe27e58, hood: 0x45464f, jeans: 0x3a5a86, shoe: 0xf6f2ea }
    const hero = (this.hero3 = new THREE.Group()); s.add(hero)
    hero.add(makeRocket({ ...kit, seg: 7 })); this.claude = makeClaude(kit); this.claude.position.y = 2.98; hero.add(this.claude)
    this.flame = makeFlame({ seg: 5, c1: 0x57b8ff, c2: 0xb5e6ff, c3: 0xffffff }); this.flame.position.y = 0.05; hero.add(this.flame)
    this.cam = new THREE.PerspectiveCamera(32, W / H, 0.1, 200)
  },
  render(t, ctx, dur) {
    const u = t / dur
    // swerves left, right, left: each rock goes by on the side it just left
    const sway = Math.sin(u * Math.PI * 3) * 1.25
    const h = this.hero3; h.position.set(sway, 0, 0); h.rotation.z = -Math.cos(u * Math.PI * 3) * 0.3; h.rotation.y = 0.32 * Math.cos(u * Math.PI * 3)
    const a = Math.sin(t * 15) * 8
    this.claude.userData.pose({ al: 125 + a, ar: -125 + a, ll: 12, lr: -12, tilt: -Math.cos(u * Math.PI * 3) * 14 })
    this.flame.scale.setScalar(0.92 + 0.13 * Math.sin(t * 60))
    this.rocks.forEach((m, i) => {
      const d = m.userData, p = (u - d.at + 0.5) // 0.5 = level with the rocket
      m.position.set(d.x * (1 + Math.max(0, p - 0.5) * 0.4), d.y + (0.5 - p) * 9, lerp(-24, 12, clamp(p)))
      m.rotation.set(t * (0.8 + i * 0.13), t * (0.6 + i * 0.1), i)
    })
    this.moon.scale.setScalar(0.66 + 0.5 * ss(0.3, 1, u)); this.moon.rotation.y = t * 0.12; this.moon.position.y = 18 - u * 2
    this.planet.rotation.y = t * 0.2
    this.cam.position.set(Math.sin(u * 6) * 0.6, 3.1, 21); this.cam.lookAt(0, 3.6, 0)
    const rr = this.r; rr.shadowMap.enabled = true; rr.shadowMap.needsUpdate = true
    rr.setSize(this.W, this.H, false); rr.render(this.scene, this.cam)
    ctx.drawImage(rr.domElement, 0, 0, this.W, this.H)
  },
}
