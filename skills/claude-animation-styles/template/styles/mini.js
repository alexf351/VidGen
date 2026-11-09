// 10 MINIATURE DIORAMA. It was a model all along. The camera pulls back from the tiny moon to the whole desk, with tilt-shift blur.
import * as THREE from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { makeClaude, makeRocket } from '../lib/three-claude.js'
import { canvas, clamp, ss, rng, easeOut, lerp } from '../lib/common.js'
const woodTex = () => { const c = canvas(1024, 1024), x = c.getContext('2d'), r = rng(7); x.fillStyle = '#a4703f'; x.fillRect(0, 0, 1024, 1024); for (let i = 0; i < 520; i++) { const y = r() * 1024; x.strokeStyle = `rgba(${r() > 0.5 ? '60,34,14' : '214,164,112'},${0.05 + r() * 0.15})`; x.lineWidth = 0.6 + r() * 3; x.beginPath(); x.moveTo(0, y); for (let k = 0; k <= 1024; k += 64) x.lineTo(k, y + Math.sin(k * 0.006 + i) * 11 + (r() - 0.5) * 3); x.stroke() } const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(3, 3); t.colorSpace = THREE.SRGBColorSpace; return t }
const moonTex = () => { const c = canvas(1024, 512), x = c.getContext('2d'), r = rng(19); x.fillStyle = '#bcb9ad'; x.fillRect(0, 0, 1024, 512); for (let i = 0; i < 2600; i++) { const v = 120 + r() * 110; x.fillStyle = `rgba(${v},${v},${v - 6},.34)`; x.beginPath(); x.arc(r() * 1024, r() * 512, r() * 7, 0, 7); x.fill() } for (let i = 0; i < 90; i++) { const a = r() * 1024, b = r() * 512, k = 6 + r() * 36; x.fillStyle = 'rgba(92,90,84,.62)'; x.beginPath(); x.arc(a, b, k, 0, 7); x.fill(); x.fillStyle = 'rgba(214,210,196,.6)'; x.beginPath(); x.arc(a + k * 0.14, b + k * 0.14, k * 0.76, 0, 7); x.fill() } const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping; return t }
const cardboard = (col) => { const c = canvas(128, 128), x = c.getContext('2d'), r = rng(col & 255); x.fillStyle = '#' + col.toString(16).padStart(6, '0'); x.fillRect(0, 0, 128, 128); x.strokeStyle = 'rgba(70,40,10,.17)'; for (let i = 0; i < 128; i += 5) { x.beginPath(); x.moveTo(0, i); x.lineTo(128, i + (r() - 0.5) * 2); x.stroke() } x.fillStyle = 'rgba(255,226,142,1)'; for (let a = 16; a < 110; a += 32) for (let b = 12; b < 110; b += 30) if (r() > 0.25) x.fillRect(a, b, 17, 16); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t }
const VERT = 'varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }'
const FRAG = `uniform sampler2D tex; uniform float focus,band,amt; uniform vec2 px; varying vec2 vUv;
void main(){ float d=max(0.,abs(vUv.y-focus)-band); float r=clamp(d*amt,0.,1.)*34.; vec3 c=vec3(0.); float w=0.;
 for(int i=0;i<44;i++){ float a=float(i)*2.39996; float k=sqrt(float(i)/44.)*r; c+=texture2D(tex,vUv+vec2(cos(a),sin(a))*k*px).rgb; w+=1.; }
 c/=w; c=pow(c,vec3(.97)); c*=vec3(1.03,1.0,.95); gl_FragColor=vec4(c,1.);
#include <colorspace_fragment>
}`
export default {
  name: 'miniature diorama',
  hero: 0.82,
  create({ W, H, renderer }) {
    this.W = W; this.H = H; this.r = renderer; const wide = W / H > 1
    const s = (this.scene = new THREE.Scene()); s.background = new THREE.Color(0x3a2a22)
    s.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.05).texture; s.environmentIntensity = 0.35
    s.add(new THREE.HemisphereLight(0xfff0dc, 0x4a3425, 1.0))
    const lamp = new THREE.SpotLight(0xffdfb0, 520, 60, 0.62, 0.65, 1.7); lamp.position.set(-9, 19, 7); lamp.castShadow = true; lamp.shadow.mapSize.set(2048, 2048); lamp.shadow.radius = 6; lamp.shadow.bias = -0.0004; lamp.target.position.set(0, 0, 0); s.add(lamp, lamp.target)
    const rimL = new THREE.DirectionalLight(0xa8c4ff, 0.7); rimL.position.set(10, 8, -8); s.add(rimL)
    const std = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.62, ...o })
    const sh = (m) => { m.castShadow = true; m.receiveShadow = true; return m }
    const desk = sh(new THREE.Mesh(new THREE.PlaneGeometry(90, 90), std(0xffffff, { map: woodTex(), roughness: 0.48 }))); desk.rotation.x = -Math.PI / 2; s.add(desk)
    const nightC = canvas(1024, 1024), nx = nightC.getContext('2d'), nr = rng(23), ng = nx.createLinearGradient(0, 0, 0, 1024); ng.addColorStop(0, '#0e1236'); ng.addColorStop(0.7, '#27306b'); ng.addColorStop(1, '#4a3f73'); nx.fillStyle = ng; nx.fillRect(0, 0, 1024, 1024)
    for (let i = 0; i < 420; i++) { nx.fillStyle = `rgba(255,${235 + nr() * 20},${200 + nr() * 50},${0.45 + nr() * 0.55})`; nx.beginPath(); nx.arc(nr() * 1024, nr() * 1024, 0.8 + nr() * 2.6, 0, 7); nx.fill() }
    const nightT = new THREE.CanvasTexture(nightC); nightT.colorSpace = THREE.SRGBColorSpace
    const wallM = new THREE.Mesh(new THREE.PlaneGeometry(110, 54), std(0xffffff, { map: nightT, roughness: 0.95 })); wallM.position.set(0, 26, -14); s.add(wallM)
    // the moon on its peg
    const moon = sh(new THREE.Mesh(new THREE.SphereGeometry(2.1, 64, 48), std(0xc2c2c2, { map: moonTex(), roughness: 0.95 }))); moon.position.set(0, 4.4, 0); s.add(moon)
    const peg = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 2.6, 16), std(0x7c5a37))); peg.position.set(0, 1.3, 0); s.add(peg)
    const base = sh(new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.7, 0.36, 40), std(0x5f4023, { roughness: 0.4 }))); base.position.y = 0.18; s.add(base)
    // tiny rocket and Claude on top, with the flag
    const kit = { seg: 20, selfShadow: true, mat: (c) => std(c, { roughness: 0.4 }) }
    const hero = new THREE.Group(); hero.position.set(0.52, 6.26, 0.5); hero.rotation.z = -0.14; hero.scale.setScalar(0.22); s.add(hero); hero.add(makeRocket(kit)); this.hero3 = hero
    const cl = (this.claude = makeClaude(kit)); cl.position.set(-0.72, 6.42, 0.5); cl.scale.setScalar(0.2); cl.rotation.z = 0.26; s.add(cl)
    const pole = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.8, 8), std(0xe6e2d8))); pole.position.set(-1.14, 6.5, 0.5); pole.rotation.z = 0.28; s.add(pole)
    const flagShape = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 0.24), std(0xd97757, { side: THREE.DoubleSide })); flagShape.position.set(-1.4, 6.8, 0.5); flagShape.rotation.z = 0.28; flagShape.castShadow = true; s.add(flagShape)
    // cardboard city around the base, cotton clouds on wires, stars on pins
    const palette = [0xc98a4b, 0xb97a44, 0xd6a062, 0xa86e3c, 0xcf9450]
    const r = rng(11)
    const place = [[-7.4, -2.4, 1.5, 3.4], [-5.2, -3.4, 1.3, 4.6], [-3.5, -2.5, 1.2, 2.8], [4.6, -2.5, 1.6, 3.8], [6.8, -3.4, 1.3, 5.2], [8.7, -2.4, 1.5, 3], [-9.2, -3.6, 1.6, 2.6], [2.6, -4, 1.2, 2.3], [-1.8, -5, 1.4, 3.6], [11, -3.6, 1.4, 4]]
    place.forEach(([x, z, w, h], i) => { const m = sh(new THREE.Mesh(new THREE.BoxGeometry(w, h, w), [0, 1, 2, 3, 4, 5].map(() => std(0xffffff, { map: cardboard(palette[i % 5]), roughness: 0.9 })))); m.position.set(x, h / 2, z); m.rotation.y = (r() - 0.5) * 0.2; s.add(m) })
    const cottonG = new THREE.IcosahedronGeometry(1, 3), cottonM = std(0xfbf7ef, { roughness: 1 })
    const cotton = (x, y, z, k) => { const g = new THREE.Group(); for (let i = 0; i < 7; i++) { const m = sh(new THREE.Mesh(cottonG, cottonM)); const rad = (0.34 + r() * 0.34) * k; m.scale.setScalar(rad); m.position.set((i - 3) * 0.3 * k, r() * 0.34 * k, (r() - 0.5) * 0.5 * k); g.add(m) } g.position.set(x, y, z); s.add(g); const w = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, y, 6), std(0x8a8a8a, { metalness: 0.7 }))); w.position.set(x, y / 2, z); s.add(w) }
    // the backyard the story started in, built tiny at the foot of the moon
    const yardWall = sh(new THREE.Mesh(new THREE.BoxGeometry(1.5, 1.1, 1.2), std(0xe6dcc6))); const yx = wide ? -3.6 : 2.7; yardWall.position.set(yx, 0.55, 3.6); s.add(yardWall)
    const yardRoof = sh(new THREE.Mesh(new THREE.ConeGeometry(1.25, 0.8, 4), std(0xb5432f))); yardRoof.rotation.y = Math.PI / 4; yardRoof.position.set(yx, 1.5, 3.6); s.add(yardRoof)
    const lawn = sh(new THREE.Mesh(new THREE.CylinderGeometry(2.3, 2.4, 0.1, 40), std(0x4f8a45, { roughness: 1 }))); lawn.position.set(yx, 0.05, 3.6); s.add(lawn)
    yardWall.position.y = 0.65; yardRoof.position.y = 1.6
    cotton(-5.2, 6.6, -1.2, 1.6); cotton(5.6, 7.4, -1.4, 1.8); cotton(-3.2, 8.4, -2.2, 1.2); cotton(7.8, 5.2, -0.6, 1.2)
    const starG = new THREE.OctahedronGeometry(0.2), starM = std(0xf7d66a, { emissive: 0x77541a, roughness: 0.3 })
    for (const [x, y, z] of [[-3, 7, -0.8], [3, 7.8, -1], [-6.8, 8.6, -2], [7, 9.4, -2.4], [2.2, 9.8, -2], [-1.8, 9.2, -1.8]]) { const m = sh(new THREE.Mesh(starG, starM)); m.position.set(x, y, z); s.add(m); const w = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, y, 5), std(0x9a9a9a)); w.position.set(x, y / 2, z); s.add(w) }
    // the desk things that give the scale away: a pencil, a mug, a ruler
    const pencil = new THREE.Group()
    const shaft = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 7.6, 6), std(0xf5c02e))); shaft.rotation.z = Math.PI / 2; pencil.add(shaft)
    const tip = sh(new THREE.Mesh(new THREE.ConeGeometry(0.17, 0.62, 6), std(0xd9b07a))); tip.rotation.z = -Math.PI / 2; tip.position.x = 4.1; pencil.add(tip)
    const eraser = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.4, 12), std(0xe58a97))); eraser.rotation.z = Math.PI / 2; eraser.position.x = -4; pencil.add(eraser)
    pencil.position.set(wide ? 5.6 : 2.8, 0.18, wide ? 7.8 : 8.2); pencil.rotation.y = 0.5; s.add(pencil)
    const mug = sh(new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.42, 3.2, 44, 1, true), std(0xe6e0d2, { side: THREE.DoubleSide, roughness: 0.28 }))); mug.position.set(wide ? -8.4 : -4.7, 1.6, wide ? 6 : 7); s.add(mug)
    const coffee = new THREE.Mesh(new THREE.CircleGeometry(1.46, 40), std(0x3d2413, { roughness: 0.2 })); coffee.rotation.x = -Math.PI / 2; coffee.position.set(wide ? -8.4 : -4.7, 2.9, wide ? 6 : 7); s.add(coffee)
    const handle = sh(new THREE.Mesh(new THREE.TorusGeometry(0.72, 0.16, 12, 28), std(0xe6e0d2, { roughness: 0.28 }))); handle.position.set(wide ? -6.8 : -3.1, 1.7, wide ? 6.4 : 7.4); handle.rotation.y = -0.3; s.add(handle)
    const ruler = sh(new THREE.Mesh(new THREE.BoxGeometry(11, 0.08, 1.2), std(0xe8d48a, { roughness: 0.4 }))); ruler.position.set(7.4, 0.04, 3.6); ruler.rotation.y = -0.26; s.add(ruler)
    this.cam = new THREE.PerspectiveCamera(28, W / H, 0.05, 200)
    this.rt = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 4 })
    this.post = new THREE.Scene(); this.pc = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
    this.pm = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms: { tex: { value: this.rt.texture }, focus: { value: 0.5 }, band: { value: 0.1 }, amt: { value: 3.2 }, px: { value: new THREE.Vector2(1 / W, 1 / H) } }, depthTest: false, depthWrite: false })
    this.post.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.pm))
  },
  render(t, ctx, dur) {
    const u = t / dur, k = ss(0.04, 0.8, u), e = k * k * (3 - 2 * k)
    // from nose to nose with Claude, all the way back to the whole desk
    const cl = this.claude.userData, wv = Math.sin(t * 9) * 14
    cl.pose({ al: 125, ar: -110 + wv, ll: 6, lr: -6, tilt: wv * 0.4 })
    const near = new THREE.Vector3(-0.3, 7.3, 6.6), far = new THREE.Vector3(0.6, 12.5, 37)
    this.cam.position.lerpVectors(near, far, e)
    const lNear = new THREE.Vector3(-0.32, 6.7, 0.5), lFar = new THREE.Vector3(0, 4.2, 0)
    this.cam.lookAt(lNear.clone().lerp(lFar, e))
    const rr = this.r; rr.shadowMap.enabled = true; rr.shadowMap.needsUpdate = true
    rr.toneMapping = THREE.ACESFilmicToneMapping; rr.toneMappingExposure = 1.1
    rr.setSize(this.W, this.H, false)
    rr.setRenderTarget(this.rt); rr.render(this.scene, this.cam); rr.setRenderTarget(null)
    rr.toneMapping = THREE.NoToneMapping
    this.pm.uniforms.focus.value = lerp(0.5, 0.56, e); this.pm.uniforms.band.value = lerp(0.12, 0.16, e); this.pm.uniforms.amt.value = lerp(2.2, 3.0, e)
    rr.render(this.post, this.pc)
    ctx.drawImage(rr.domElement, 0, 0, this.W, this.H)
  },
}
