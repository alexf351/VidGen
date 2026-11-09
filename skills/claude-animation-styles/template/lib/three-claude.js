// The same character and rocket in 3D. `kit` decides how round it is and what it's made of.
import * as THREE from 'three'
const D = (d) => (d * Math.PI) / 180

export function makeClaude(kit) {
  const m = kit.mat, seg = kit.seg ?? 16, g = new THREE.Group()
  const body = new THREE.Group(); g.add(body)
  const cap = (r, l, mat) => new THREE.Mesh(new THREE.CapsuleGeometry(r, l, Math.max(2, seg >> 2), seg), mat)
  const hood = m(kit.hood ?? 0x3a3a3e), jeans = m(kit.jeans ?? 0x2f4258), star = m(kit.star ?? 0xd97757), shoe = m(kit.shoe ?? 0xf2efe8)
  const torso = cap(0.42, 0.26, hood); torso.position.y = 1.0; torso.scale.set(1, 1, 0.74); body.add(torso)
  const hoodBack = new THREE.Mesh(new THREE.SphereGeometry(0.24, seg, seg), hood); hoodBack.position.set(0, 1.46, -0.08); body.add(hoodBack)
  const limb = (r, l, mat, x, y) => { const j = new THREE.Group(); j.position.set(x, y, 0); const c = cap(r, l, mat); c.position.y = -(l / 2 + r * 0.6); j.add(c); body.add(j); return j }
  const armL = limb(0.125, 0.46, hood, -0.43, 1.26), armR = limb(0.125, 0.46, hood, 0.43, 1.26)
  const handMesh = (j) => { const h = new THREE.Mesh(new THREE.SphereGeometry(0.14, seg, seg), star); h.position.y = -0.76; j.add(h) }
  handMesh(armL); handMesh(armR)
  const legL = limb(0.155, 0.4, jeans, -0.19, 0.72), legR = limb(0.155, 0.4, jeans, 0.19, 0.72)
  const foot = (j) => { const f = new THREE.Mesh(new THREE.SphereGeometry(0.18, seg, seg), shoe); f.scale.set(1, 0.66, 1.5); f.position.set(0, -0.7, 0.08); j.add(f) }
  foot(legL); foot(legR)
  // the starburst head: 8 thick rounded rays
  const head = new THREE.Group(); head.position.y = 2.02
  for (let i = 0; i < 8; i++) {
    const ray = cap(0.205, 0.46, star); const a = D(i * 45)
    ray.position.set(Math.sin(a) * 0.46, Math.cos(a) * 0.46, 0); ray.rotation.z = -a; ray.scale.z = 0.72; head.add(ray)
  }
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.42, seg, seg), star); core.scale.z = 0.7; head.add(core)
  body.add(head)
  g.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = !!kit.selfShadow } })
  g.userData = { armL, armR, legL, legR, head, body }
  g.userData.pose = ({ al = 125, ar = -125, ll = 6, lr = -6, tilt = 0, lean = 0 } = {}) => {
    armL.rotation.z = D(-al); armR.rotation.z = D(-ar); legL.rotation.z = D(ll); legR.rotation.z = D(lr); head.rotation.z = D(tilt); body.rotation.z = D(lean)
  }
  g.userData.pose()
  return g
}

export function makeRocket(kit) {
  const m = kit.mat, seg = kit.seg ?? 24, g = new THREE.Group()
  const prof = [[0.0, 3.0], [0.2, 2.95], [0.42, 2.75], [0.58, 2.42], [0.66, 2.0], [0.68, 1.5], [0.64, 1.0], [0.52, 0.55], [0.4, 0.34], [0, 0.34]].map(([x, y]) => new THREE.Vector2(x, y)).reverse() // bottom to top, or the lighting comes out inside out
  const bodyG = new THREE.LatheGeometry(kit.smooth === false ? prof : new THREE.SplineCurve(prof).getPoints(40), seg)
  const body = new THREE.Mesh(bodyG, m(kit.body ?? 0xf4f1ea)); g.add(body)
  const noseProf = [[0.0, 3.02], [0.2, 2.97], [0.42, 2.77], [0.55, 2.5], [0.6, 2.32], [0, 2.32]].map(([x, y]) => new THREE.Vector2(x, y)).reverse()
  const nose = new THREE.Mesh(new THREE.LatheGeometry(noseProf, seg), m(kit.nose ?? 0xd8432f)); g.add(nose)
  const fin = (a) => {
    const s = new THREE.Shape(); s.moveTo(0, 0); s.quadraticCurveTo(0.56, -0.1, 0.6, -0.72); s.lineTo(0.12, -0.42); s.closePath()
    const f = new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: 0.1, bevelEnabled: false }), m(kit.nose ?? 0xd8432f))
    f.geometry.translate(0, 0, -0.05); f.position.set(Math.cos(a) * 0.5, 1.02, Math.sin(a) * 0.5); f.rotation.y = -a; g.add(f)
  }
  for (let i = 0; i < 3; i++) fin(D(i * 120 + 30))
  const noz = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.38, 0.34, seg), m(kit.nozzle ?? 0x4a4a50)); noz.position.y = 0.17; g.add(noz)
  const rim = new THREE.Mesh(new THREE.TorusGeometry(0.28, 0.055, Math.max(6, seg >> 2), seg), m(kit.rim ?? 0xd8432f)); rim.position.set(0, 1.7, 0.7); g.add(rim)
  const glass = new THREE.Mesh(new THREE.CircleGeometry(0.27, seg), m(kit.glass ?? 0x7ac6ee)); glass.position.set(0, 1.7, 0.705); g.add(glass)
  g.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = !!kit.selfShadow } })
  return g
}

// A flame you can scale. Its tip points down from y = 0.
export function makeFlame(kit = {}) {
  const g = new THREE.Group()
  const mk = (r, h, col) => { const f = new THREE.Mesh(new THREE.ConeGeometry(r, h, kit.seg ?? 16), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: kit.opacity ?? 1 })); f.rotation.x = Math.PI; f.position.y = -h / 2; return f }
  g.add(mk(0.36, 1.9, kit.c1 ?? 0xf0642a), mk(0.24, 1.3, kit.c2 ?? 0xf8b12d), mk(0.12, 0.7, kit.c3 ?? 0xfff3c0))
  g.children[1].position.z = 0.02; g.children[2].position.z = 0.04
  return g
}
