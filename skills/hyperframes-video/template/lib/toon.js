// toon.js: the cartoon toolkit for the "toon" look. Flat 2D characters drawn in code, standing in a
// painted 3D town with black ink outlines, under a saturated sky. Everything here is a pure function of
// time: a scene builds once, then draw(t) poses every part for the moment t (seconds into the beat), so
// any frame can be rendered on its own, in any order. Uses three.js (MIT), loaded from assets/vendor.
//
//   const S = T.stage(canvas, { light: "day" });          // renderer, sky, fog, lights
//   T.ground(S); T.street(S, { length: 60 });
//   T.house(S, { x: -7, z: -6, wall: "brick" });          // a painted house with ink outlines
//   const maya = T.person(S, { name: "maya", skin: "tan", hair: "bun", hairColor: "#3b2416", shirt: "#e4573d" });
//   const cam = T.cameraPath([{ t: 0, pos: [0, 1.6, 7], look: [0, 1.3, 0] }, { t: 3, pos: [0, 1.5, 5], look: [0, 1.4, 0] }]);
//   return (t) => { maya.pose(t, { x: 0, z: 0, mood: "happy", talk: t < 1.2 }); cam.apply(S, t); S.render(); };
//
// Units are metres. y is up, the camera usually looks toward -z.

import * as THREE from "../vendor/three/three.module.js";

export { THREE };

// ------------------------------------------------------------------ maths ----

/** A seeded random generator: rng() gives 0..1, the same sequence for the same seed. */
export function rng(seed) {
  let a = typeof seed === "number" ? seed >>> 0 : hash(String(seed));
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

export const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, k) => a + (b - a) * k;
/** 0 before a, 1 after b, a smootherstep glide between. */
export const glide = (t, a, b) => {
  const k = clamp((t - a) / Math.max(1e-6, b - a));
  return k * k * k * (k * (k * 6 - 15) + 10);
};
/** A pop: 0 before t0, overshoots to about 1.12, settles on 1 by t0 + dur. */
export const pop = (t, t0, dur = 0.35) => {
  const k = clamp((t - t0) / dur);
  if (k <= 0) return 0;
  const c = 2.2;
  return 1 + (c + 1) * Math.pow(k - 1, 3) + c * Math.pow(k - 1, 2);
};
const mix3 = (a, b, k) => [lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k)];

// ------------------------------------------------------------------ light ----

/** The two lights the look has. day: high warm sun, blue sky. golden: low sun behind, peach sky. */
export const LIGHTS = {
  day: { skyTop: "#3e7fd2", horizon: "#b8d0ec", fogNear: 28, fogFar: 260, sun: [0.55, 0.78, 0.3],
         sunColor: "#fff1dc", sunI: 2.1, skyI: 1.05, groundTint: "#6d6a78", tint: "#ffffff" },
  golden: { skyTop: "#ffc47c", horizon: "#8a6f8a", fogNear: 22, fogFar: 200, sun: [0.1, 0.22, -0.97],
            sunColor: "#ffb36b", sunI: 2.4, skyI: 0.75, groundTint: "#444380", tint: "#ffd9b0" },
  night: { skyTop: "#0b1430", horizon: "#2b3a6b", fogNear: 18, fogFar: 140, sun: [-0.4, 0.8, 0.4],
           sunColor: "#9fb6ff", sunI: 0.9, skyI: 0.55, groundTint: "#1d2340", tint: "#9fb3e8" },
};

/** Painted colours: pick by name or pass any hex. Muted, never lemon or lavender. */
export const PAINT = {
  brick: "#b5583f", cream: "#e8dcc0", ochre: "#d39a45", terracotta: "#c8693f", sage: "#8fae84",
  sky: "#7fb0d8", rose: "#d98b84", slate: "#5d6a7a", roof: "#5a3a3a", roofBlue: "#3f5470",
  roofGreen: "#4f6b4a", stone: "#b7ab98", road: "#5a5862", walk: "#c9bfae", grass: "#7fb05a",
  wood: "#a8743f", glass: "#26405f", trim: "#f2ead8", ink: "#0b0a0c",
};
const paint = (c) => (c && PAINT[c]) || c || "#cccccc";

// --------------------------------------------------------------- the stage ----

/**
 * The renderer, the sky, the fog and the lights, on a 1080 x 1920 canvas.
 * opts.light: "day" | "golden" | "night". opts.fov: the camera's vertical field of view.
 * Returns { scene, camera, renderer, light, add(obj), render(), billboards }.
 */
export function stage(canvas, opts = {}) {
  const L = LIGHTS[opts.light || "day"];
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, alpha: false });
  renderer.setPixelRatio(1);
  renderer.setSize(opts.width || 1080, opts.height || 1920, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(new THREE.Color(L.horizon), L.fogNear, L.fogFar);
  const camera = new THREE.PerspectiveCamera(opts.fov || 38, (opts.width || 1080) / (opts.height || 1920), 0.1, 900);

  // The sky: a gradient dome, horizon at eye level, deep colour overhead.
  const sky = new THREE.Mesh(
    new THREE.SphereGeometry(600, 32, 16),
    new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: { top: { value: new THREE.Color(L.skyTop) }, hor: { value: new THREE.Color(L.horizon) } },
      vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: "uniform vec3 top; uniform vec3 hor; varying vec3 vP; void main(){ float k = pow(clamp(vP.y*1.6,0.0,1.0),0.7); gl_FragColor = vec4(mix(hor*1.12, top, k),1.0); }",
    }));
  sky.renderOrder = -10;
  scene.add(sky);

  const hemi = new THREE.HemisphereLight(new THREE.Color(L.skyTop), new THREE.Color(L.groundTint), L.skyI);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(new THREE.Color(L.sunColor), L.sunI);
  sun.position.set(L.sun[0] * 100, L.sun[1] * 100, L.sun[2] * 100);
  scene.add(sun);

  const S = {
    scene, camera, renderer, light: L, lightName: opts.light || "day", sky, sun, hemi,
    billboards: [],
    add(obj) { scene.add(obj); return obj; },
    render() {
      for (const b of S.billboards) b.face(camera);
      sky.position.copy(camera.position);
      renderer.render(scene, camera);
    },
  };
  return S;
}

// Two-tone cel shading: a lit side and a shade side, with a soft step between.
let _ramp = null;
function ramp() {
  if (_ramp) return _ramp;
  const data = new Uint8Array([92, 92, 92, 255, 200, 200, 200, 255, 255, 255, 255, 255]);
  _ramp = new THREE.DataTexture(data, 3, 1, THREE.RGBAFormat);
  _ramp.minFilter = THREE.NearestFilter;
  _ramp.magFilter = THREE.NearestFilter;
  _ramp.needsUpdate = true;
  return _ramp;
}

/** A painted surface: cel shaded, takes fog. */
export function mat(color, opts = {}) {
  return new THREE.MeshToonMaterial({ color: new THREE.Color(paint(color)), gradientMap: ramp(), ...opts });
}

/** A surface that ignores the light (screens, glowing windows, signs). */
export function flat(color, opts = {}) {
  return new THREE.MeshBasicMaterial({ color: new THREE.Color(paint(color)), ...opts });
}

const INK = new THREE.MeshBasicMaterial({ color: new THREE.Color(PAINT.ink), side: THREE.BackSide });

/**
 * Ink outline around a mesh: a black shell a few centimetres bigger, drawn from behind (inverted hull).
 * width in metres: 0.035 for houses near the lens, 0.02 for props, 0.06 for big far things.
 */
export function ink(mesh, width = 0.035) {
  mesh.geometry.computeBoundingBox();
  const size = new THREE.Vector3();
  mesh.geometry.boundingBox.getSize(size);
  const hull = new THREE.Mesh(mesh.geometry, INK);
  hull.scale.set(1 + (2 * width) / Math.max(size.x, 1e-3), 1 + (2 * width) / Math.max(size.y, 1e-3),
    1 + (2 * width) / Math.max(size.z, 1e-3));
  const c = new THREE.Vector3();
  mesh.geometry.boundingBox.getCenter(c);
  hull.position.set(                                               // keep the shell centred on the part
    c.x * (1 - hull.scale.x), c.y * (1 - hull.scale.y), c.z * (1 - hull.scale.z));
  hull.name = (mesh.name || "part") + "_ink";
  mesh.add(hull);
  return mesh;
}

/** A box with its base at y: (w, h, d) metres, a colour, an outline. */
export function box(w, h, d, color, opts = {}) {
  const g = new THREE.BoxGeometry(w, h, d);
  g.translate(0, h / 2, 0);
  const m = new THREE.Mesh(g, opts.flat ? flat(color) : mat(color));
  if (opts.ink !== false) ink(m, opts.ink || 0.03);
  return m;
}

function place(obj, o) {
  obj.position.set(o.x || 0, o.y || 0, o.z || 0);
  if (o.rotY) obj.rotation.y = (o.rotY * Math.PI) / 180;
  if (o.scale) obj.scale.setScalar(o.scale);
  return obj;
}

// ----------------------------------------------------------------- the world ----

/** The ground: grass to the horizon. */
export function ground(S, opts = {}) {
  const g = new THREE.Mesh(new THREE.PlaneGeometry(900, 900), mat(opts.color || "grass"));
  g.rotation.x = -Math.PI / 2;
  g.name = "ground";
  return S.add(g);
}

/** A street along z with pavements either side, centred on x. */
export function street(S, opts = {}) {
  const len = opts.length || 80, w = opts.width || 6, x = opts.x || 0, z = opts.z || -len / 2 + 10;
  const grp = new THREE.Group();
  const road = new THREE.Mesh(new THREE.PlaneGeometry(w, len), mat("road"));
  road.rotation.x = -Math.PI / 2; road.position.set(x, 0.01, z); grp.add(road);
  for (const side of [-1, 1]) {
    const walk = box(2.2, 0.12, len, "walk", { ink: 0.02 });
    walk.position.set(x + side * (w / 2 + 1.1), 0, z); grp.add(walk);
  }
  for (let i = 0; i < len / 4; i++) {                              // the dashed centre line
    const dash = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 1.6), flat("#e9e2cf"));
    dash.rotation.x = -Math.PI / 2; dash.position.set(x, 0.02, z + len / 2 - 2 - i * 4); grp.add(dash);
  }
  grp.name = "street";
  return S.add(grp);
}

/**
 * A painted town house. opts: x, z, rotY (degrees; 0 faces +z, the camera's usual side), w, d, h
 * (metres), wall, roof, trim (colours or PAINT names), floors, seed, door (true by default).
 */
export function house(S, opts = {}) {
  const r = rng(opts.seed ?? hash(`${opts.x},${opts.z}`));
  const w = opts.w || 6 + r() * 2, d = opts.d || 6, floors = opts.floors || (r() < 0.5 ? 2 : 3);
  const h = opts.h || floors * 2.8 + 0.6;
  const walls = ["brick", "cream", "ochre", "terracotta", "sage", "rose", "sky"];
  const wall = opts.wall || walls[Math.floor(r() * walls.length)];
  const roofC = opts.roof || ["roof", "roofBlue", "roofGreen"][Math.floor(r() * 3)];
  const trim = opts.trim || "trim";
  const g = new THREE.Group();
  g.name = opts.name || "house";
  const body = box(w, h, d, wall, { ink: 0.04 }); body.name = "walls"; g.add(body);
  const plinth = box(w + 0.16, 0.5, d + 0.16, "stone", { ink: 0.03 }); g.add(plinth);
  const cornice = box(w + 0.3, 0.22, d + 0.3, trim, { ink: 0.03 }); cornice.position.y = h - 0.22; g.add(cornice);

  // A gable roof: a triangular prism along x.
  const rh = opts.roofHeight || 1.6 + r() * 0.8;
  const shape = new THREE.Shape([new THREE.Vector2(-d / 2 - 0.35, 0), new THREE.Vector2(d / 2 + 0.35, 0), new THREE.Vector2(0, rh)]);
  const rg = new THREE.ExtrudeGeometry(shape, { depth: w + 0.4, bevelEnabled: false });
  rg.translate(0, 0, -(w + 0.4) / 2);
  rg.rotateY(Math.PI / 2);
  const roof = new THREE.Mesh(rg, mat(roofC)); roof.position.y = h; ink(roof, 0.04); roof.name = "roof"; g.add(roof);
  if (r() < 0.8) {
    const ch = box(0.6, 1.4, 0.6, wall, { ink: 0.03 }); ch.position.set(w * (r() < 0.5 ? -0.3 : 0.3), h + rh * 0.35, -d * 0.1);
    g.add(ch);
  }

  // Windows on the front (+z) face, a door at the bottom.
  const cols = Math.max(2, Math.round(w / 2.2));
  for (let f = 0; f < floors; f++) {
    for (let c = 0; c < cols; c++) {
      if (f === 0 && opts.door !== false && c === Math.floor(cols / 2)) continue;
      const wx = -w / 2 + (w / cols) * (c + 0.5), wy = 0.9 + f * 2.8;
      const frame = box(1.1, 1.5, 0.08, trim, { ink: 0.02 }); frame.position.set(wx, wy, d / 2 + 0.02); g.add(frame);
      const pane = box(0.85, 1.25, 0.06, opts.lit ? "#ffd48a" : "glass", { ink: false, flat: !!opts.lit });
      pane.position.set(wx, wy + 0.12, d / 2 + 0.06); g.add(pane);
      const sill = box(1.3, 0.12, 0.25, trim, { ink: 0.015 }); sill.position.set(wx, wy - 0.05, d / 2 + 0.1); g.add(sill);
    }
  }
  if (opts.door !== false) {
    const dx = -w / 2 + (w / cols) * (Math.floor(cols / 2) + 0.5);
    const door = box(1.2, 2.2, 0.1, opts.doorColor || ["#2f5d50", "#7a2e2e", "#2b3f66"][Math.floor(r() * 3)], { ink: 0.025 });
    door.position.set(dx, 0.45, d / 2 + 0.03); g.add(door);
    const step = box(1.6, 0.25, 0.5, "stone", { ink: 0.02 }); step.position.set(dx, 0.2, d / 2 + 0.25); g.add(step);
  }
  return S.add(place(g, opts));
}

/** A round tree: trunk and two or three leafy blobs. */
export function tree(S, opts = {}) {
  const r = rng(opts.seed ?? hash(`t${opts.x},${opts.z}`));
  const s = opts.size || 1;
  const g = new THREE.Group(); g.name = "tree";
  const trunkG = new THREE.CylinderGeometry(0.16 * s, 0.24 * s, 2.2 * s, 8); trunkG.translate(0, 1.1 * s, 0);
  const trunk = new THREE.Mesh(trunkG, mat("wood")); ink(trunk, 0.03); g.add(trunk);
  const greens = ["#5f9a45", "#6aa64c", "#4f8a3e"];
  const n = 2 + Math.floor(r() * 2);
  for (let i = 0; i < n; i++) {
    const rad = (1.0 + r() * 0.5) * s;
    const geo = new THREE.IcosahedronGeometry(rad, 1);
    const leaf = new THREE.Mesh(geo, mat(opts.color || greens[i % 3]));
    leaf.position.set((r() - 0.5) * 1.1 * s, 2.6 * s + i * 0.7 * s, (r() - 0.5) * 0.8 * s);
    ink(leaf, 0.04); g.add(leaf);
  }
  return S.add(place(g, opts));
}

/** A street lamp. */
export function lamp(S, opts = {}) {
  const g = new THREE.Group(); g.name = "lamp";
  const pole = box(0.12, 3.6, 0.12, "#2e3a3f", { ink: 0.015 }); g.add(pole);
  const head = box(0.5, 0.45, 0.5, opts.on ? "#ffe2a0" : "#2e3a3f", { ink: 0.02, flat: !!opts.on }); head.position.y = 3.6; g.add(head);
  return S.add(place(g, opts));
}

/** Soft puffy clouds high in the sky. */
export function clouds(S, opts = {}) {
  const r = rng(opts.seed || 7);
  const g = new THREE.Group(); g.name = "clouds";
  const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(opts.color || "#ffffff"), fog: false });
  for (let i = 0; i < (opts.count || 7); i++) {
    const c = new THREE.Group();
    for (let k = 0; k < 4; k++) {
      const b = new THREE.Mesh(new THREE.SphereGeometry(6 + r() * 5, 16, 10), m);
      b.position.set(k * 7 - 10, r() * 3, r() * 3); b.scale.y = 0.55; c.add(b);
    }
    c.position.set((r() - 0.5) * 300, 55 + r() * 40, -150 - r() * 200);
    g.add(c);
  }
  return S.add(g);
}

/** A phone (or any screen) showing a real picture, e.g. "assets/screens/learn.jpg". Await it. */
export async function screen(S, opts = {}) {
  const tex = await loadTexture(opts.src);
  const w = opts.w || 0.36, h = opts.h || w * (tex.image.height / tex.image.width);
  const g = new THREE.Group(); g.name = opts.name || "phone";
  const bezel = box(w + 0.03, h + 0.03, 0.025, "#0b0d10", { ink: 0.008 }); bezel.position.y = -(h + 0.03) / 2; g.add(bezel);
  const face = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, fog: false }));
  face.position.z = 0.014; g.add(face);
  return S.add(place(g, opts));
}

const _textures = new Map();
/** Load a picture as a texture (sRGB); resolves when it can be drawn. */
export function loadTexture(src) {
  if (_textures.has(src)) return _textures.get(src);
  const p = new Promise((resolve, reject) => {
    new THREE.TextureLoader().load(src, (t) => { t.colorSpace = THREE.SRGBColorSpace; resolve(t); }, undefined,
      () => reject(new Error(`could not load ${src}`)));
  });
  _textures.set(src, p);
  return p;
}

// ---------------------------------------------------------------- the camera ----

/**
 * A camera move from keys: [{ t, pos: [x,y,z], look: [x,y,z], fov?, roll? (degrees), cut? }].
 * Between keys the camera glides (smootherstep). cut: true jumps to that key instead.
 * Every key also creeps: a held camera still pushes in about 0.25 % a frame, so nothing freezes.
 * shake(t0, amount): an impact, flipping sign every frame and dying in 7 frames.
 */
export function cameraPath(keys, opts = {}) {
  const ks = [...keys].sort((a, b) => a.t - b.t);
  const creep = opts.creep ?? 0.07;                     // metres per second toward the look point
  const shakes = [];
  const self = {
    keys: ks,
    shake(t0, amount = 0.06) { shakes.push([t0, amount]); return self; },
    at(t) {
      let i = 0;
      while (i < ks.length - 1 && ks[i + 1].t <= t) i++;
      const a = ks[i], b = ks[Math.min(i + 1, ks.length - 1)];
      let k = 0;
      if (b !== a && !b.cut) k = glide(t, a.t, b.t);
      else if (b !== a && b.cut && t >= b.t) k = 1;
      const end = b !== a && b.cut ? a : b;
      const pos = mix3(a.pos, end.pos, k), look = mix3(a.look, end.look, k);
      const since = t - (k >= 1 ? b.t : a.t);
      const dir = [look[0] - pos[0], look[1] - pos[1], look[2] - pos[2]];
      const len = Math.hypot(...dir) || 1;
      const push = Math.min(since * creep, len * 0.25);
      const p = [pos[0] + (dir[0] / len) * push, pos[1] + (dir[1] / len) * push, pos[2] + (dir[2] / len) * push];
      let jx = 0, jy = 0;
      for (const [t0, amt] of shakes) {
        const f = Math.floor((t - t0) * 30);
        if (f >= 0 && f < 7) { const s = (f % 2 ? -1 : 1) * amt * (1 - f / 7); jx += s; jy -= s * 0.6; }
      }
      return { pos: [p[0] + jx, p[1] + jy, p[2]], look, fov: lerp(a.fov || 38, end.fov || a.fov || 38, k),
               roll: lerp(a.roll || 0, end.roll || 0, k) };
    },
    apply(S, t) {
      const c = self.at(t);
      S.camera.position.set(...c.pos);
      S.camera.up.set(0, 1, 0);
      S.camera.lookAt(new THREE.Vector3(...c.look));
      if (c.roll) S.camera.rotateZ((c.roll * Math.PI) / 180);
      if (S.camera.fov !== c.fov) { S.camera.fov = c.fov; S.camera.updateProjectionMatrix(); }
    },
  };
  return self;
}

// ------------------------------------------------------------- the characters ----

// A character is a flat card drawn with Canvas2D on a 600 x 1000 design canvas (soles at y = 975),
// stood up in the world, always turned to face the camera, lit by the scene's light colour.

const CARD_W = 600, CARD_H = 1000, SOLE = 975;
const PLUM = "#241726";
export const SKIN = { pale: "#f6dcc6", light: "#f0c9a6", tan: "#d9a477", brown: "#a8714a", deep: "#6e4429" };

function card(S, draw, heightM, name) {
  const canvas = document.createElement("canvas");
  canvas.width = CARD_W; canvas.height = CARD_H;
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const scale = heightM / SOLE;                                  // metres per design pixel
  const geo = new THREE.PlaneGeometry(CARD_W * scale, CARD_H * scale);
  geo.translate(0, (CARD_H / 2 - (CARD_H - SOLE)) * scale, 0);  // the soles sit on y = 0
  const tint = new THREE.Color(S.light.tint);
  const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, transparent: true, alphaTest: 0.04, color: tint, fog: true }));
  m.name = name;
  const g = new THREE.Group(); g.name = name;
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.34 * (heightM / 1.7), 24),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.32, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.012; shadow.scale.set(1, 0.55, 1);
  g.add(shadow); g.add(m);
  S.add(g);
  const bb = {
    group: g, mesh: m, canvas, ctx: canvas.getContext("2d"), tex, flip: 1,
    face(camera) {                                               // turn about y to face the camera
      const p = new THREE.Vector3(); g.getWorldPosition(p);
      m.rotation.y = Math.atan2(camera.position.x - p.x, camera.position.z - p.z);
      m.scale.x = bb.flip;
    },
    redraw(fn) { bb.ctx.clearRect(0, 0, CARD_W, CARD_H); fn(bb.ctx); tex.needsUpdate = true; },
  };
  S.billboards.push(bb);
  return bb;
}

// The line boils: outline points jitter by a pixel or two, redrawn 12 times a second.
function boil(seed, t) {
  const r = rng(seed * 977 + Math.floor(t * 12));
  return () => (r() - 0.5) * 2.2;
}

function stroke(ctx, w, color = PLUM) { ctx.lineWidth = w; ctx.strokeStyle = color; ctx.stroke(); }

function limb(ctx, x0, y0, x1, y1, w, color) {
  ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); stroke(ctx, w + 9);
  if (color) { ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); stroke(ctx, w, color); }
}

const ARM = {          // [shoulder angle, elbow bend] in degrees; 0 hangs down, + swings forward/out
  down: [8, 6], hips: [38, -95], wave: [150, 40], up: [165, 8], point: [92, 2], shrug: [55, 85],
  phone: [28, 120], cheer: [150, -20], think: [40, 140],
};

function arm(ctx, side, sx, sy, pose, t, shirt, skin) {
  const p = Array.isArray(pose) ? pose : ARM[pose] || ARM.down;
  let a = p[0], e = p[1];
  if (pose === "wave") a += Math.sin(t * 12) * 14;
  const up = 128, lo = 118;
  const rad = (deg) => (deg * Math.PI) / 180;
  const ax = sx + side * Math.sin(rad(a)) * up, ay = sy + Math.cos(rad(a)) * up;
  const bx = ax + side * Math.sin(rad(a + e)) * lo, by = ay + Math.cos(rad(a + e)) * lo;
  limb(ctx, ax, ay, bx, by, 17, skin || null);
  limb(ctx, sx, sy, ax, ay, 30, shirt);                                                    // the sleeve over the elbow
  ctx.beginPath(); ctx.arc(bx, by, 19, 0, Math.PI * 2); ctx.fillStyle = skin || PLUM; ctx.fill();
  if (skin) stroke(ctx, 8);
  if (pose === "phone") {                                                                  // a phone in the hand
    ctx.save(); ctx.translate(bx + side * 6, by - 30); ctx.rotate(side * -0.18);
    ctx.beginPath(); ctx.roundRect(-24, -46, 48, 88, 10); ctx.fillStyle = "#15171b"; ctx.fill(); stroke(ctx, 6);
    ctx.beginPath(); ctx.roundRect(-17, -38, 34, 70, 6); ctx.fillStyle = "#5fd9e8"; ctx.fill();
    ctx.restore();
  }
  return [bx, by];
}

function face(ctx, cx, cy, hw, mood, t, talk, blinkAt, j) {
  const ex = hw * 0.26, ey = cy - 4;
  const blink = blinkAt.some((b) => t >= b && t < b + 0.13);
  ctx.fillStyle = PLUM;
  for (const s of [-1, 1]) {
    const x = cx + s * ex + j();
    if (blink || mood === "content") {
      ctx.beginPath(); ctx.moveTo(x - 14, ey + 2); ctx.quadraticCurveTo(x, mood === "content" ? ey - 10 : ey + 6, x + 14, ey + 2);
      ctx.lineCap = "round"; stroke(ctx, 7);
    } else {
      const big = mood === "shock" ? 1.35 : 1;
      ctx.beginPath(); ctx.ellipse(x, ey, 13 * big, 20 * big, 0, 0, Math.PI * 2); ctx.fill();
    }
    // brows
    const tilt = { angry: 0.45, sad: -0.4, worried: -0.4, shock: 0, smug: 0.12, happy: -0.05 }[mood] || 0;
    const by = ey - 34 - (mood === "shock" ? 12 : 0);
    ctx.beginPath(); ctx.moveTo(x - 18, by - s * tilt * 18); ctx.lineTo(x + 18, by + s * tilt * 18);
    ctx.lineCap = "round"; stroke(ctx, 7);
  }
  // the mouth
  const my = cy + hw * 0.27, open = talk ? (Math.sin(t * 22) * 0.5 + 0.5) : 0;
  ctx.beginPath();
  if (mood === "shock") { ctx.ellipse(cx, my + 4, 18, 26, 0, 0, Math.PI * 2); ctx.fillStyle = PLUM; ctx.fill(); return; }
  if (open > 0.15) {
    ctx.ellipse(cx, my, 26, 6 + open * 20, 0, 0, Math.PI * 2); ctx.fillStyle = "#5a1f2a"; ctx.fill(); stroke(ctx, 6);
    return;
  }
  const curve = { happy: 22, smug: 10, content: 12, sad: -16, angry: -12, worried: -8, neutral: 2 }[mood] ?? 2;
  if (mood === "smug") { ctx.moveTo(cx - 24, my + 2); ctx.quadraticCurveTo(cx + 6, my + 14, cx + 28, my - 6); }
  else { ctx.moveTo(cx - 30, my); ctx.quadraticCurveTo(cx, my + curve, cx + 30, my); }
  ctx.lineCap = "round"; stroke(ctx, 7);
}

function hair(ctx, style, cx, top, hw, hh, color, j) {
  if (!style || style === "bald") return;
  ctx.fillStyle = color;
  ctx.beginPath();
  if (style === "short" || style === "spiky" || style === "cap") {
    ctx.moveTo(cx - hw * 0.52, top + hh * 0.42);
    ctx.bezierCurveTo(cx - hw * 0.6, top - hh * 0.08 + j(), cx + hw * 0.6, top - hh * 0.08 + j(), cx + hw * 0.52, top + hh * 0.42);
    if (style === "spiky") for (let i = 4; i >= -4; i--) ctx.lineTo(cx + (i / 4) * hw * 0.48, top + hh * (i % 2 ? 0.18 : 0.3));
    else ctx.quadraticCurveTo(cx, top + hh * 0.12, cx - hw * 0.52, top + hh * 0.42);
  } else if (style === "long" || style === "bob") {
    const end = style === "long" ? hh * 1.25 : hh * 0.82;
    ctx.moveTo(cx - hw * 0.6, top + end);
    ctx.bezierCurveTo(cx - hw * 0.72, top - hh * 0.1, cx + hw * 0.72, top - hh * 0.1, cx + hw * 0.6, top + end);
    ctx.lineTo(cx + hw * 0.42, top + end); ctx.quadraticCurveTo(cx + hw * 0.4, top + hh * 0.22, cx, top + hh * 0.2);
    ctx.quadraticCurveTo(cx - hw * 0.4, top + hh * 0.22, cx - hw * 0.42, top + end); ctx.closePath();
  } else if (style === "bun") {
    ctx.arc(cx + j(), top - hh * 0.06, hw * 0.2, 0, Math.PI * 2); ctx.fill(); stroke(ctx, 8);
    ctx.beginPath();
    ctx.moveTo(cx - hw * 0.52, top + hh * 0.42);
    ctx.bezierCurveTo(cx - hw * 0.6, top - hh * 0.05, cx + hw * 0.6, top - hh * 0.05, cx + hw * 0.52, top + hh * 0.42);
    ctx.quadraticCurveTo(cx, top + hh * 0.14, cx - hw * 0.52, top + hh * 0.42);
  } else if (style === "curly") {
    for (let i = 0; i < 9; i++) {
      const a = Math.PI * (1.05 + (i / 8) * 0.9);
      ctx.moveTo(cx + Math.cos(a) * hw * 0.5 + hw * 0.16, top + hh * 0.38 + Math.sin(a) * hh * 0.42);
      ctx.arc(cx + Math.cos(a) * hw * 0.5, top + hh * 0.38 + Math.sin(a) * hh * 0.42, hw * 0.16 + j(), 0, Math.PI * 2);
    }
  }
  ctx.fill(); stroke(ctx, 8);
  if (style === "cap") {
    ctx.beginPath(); ctx.ellipse(cx + hw * 0.32, top + hh * 0.3, hw * 0.4, hh * 0.07, 0, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.fill(); stroke(ctx, 7);
  }
}

/**
 * A person: bean head, stick limbs, plum ink, about 3.5 heads tall.
 * opts: name, height (metres, 1.75 default), skin (SKIN name or hex), hair (short | spiky | long | bob |
 * bun | curly | cap | bald), hairColor, shirt, pants, shoes, seed.
 * Then every frame: person.pose(t, { x, z, mood, talk, walk, arms: [left, right], look: -1 | 1, hop }).
 * mood: neutral | happy | sad | angry | shock | smug | worried | content. arms: ARM names or
 * [shoulder, elbow] degrees. walk: metres per second (the legs swing, the body bobs). look: which way
 * they face (1 = right of frame). hop: a height in metres (a jump).
 */
export function person(S, opts = {}) {
  const name = opts.name || "person";
  const seed = hash(name);
  const heightM = opts.height || 1.75;
  const bb = card(S, null, heightM, name);
  const skin = SKIN[opts.skin] || opts.skin || SKIN.light;
  const shirt = paint(opts.shirt || "#3f7fd0"), pants = paint(opts.pants || "#2d3550"), shoes = opts.shoes || PLUM;
  const hairColor = opts.hairColor || "#3b2416", style = opts.hair || "short";
  const br = rng(seed);
  const blinks = []; for (let t = 0.3 + br() * 1.2; t < 120; t += 0.5 + br() * 1.8) blinks.push(t);

  const self = {
    card: bb, group: bb.group,
    pose(t, p = {}) {
      bb.group.position.set(p.x ?? self.group.position.x, (p.hop || 0), p.z ?? self.group.position.z);
      if (p.look) bb.flip = p.look < 0 ? -1 : 1;
      const walk = p.walk || 0;
      const phase = t * (walk ? 2.2 + walk * 1.4 : 0) * Math.PI;
      const bob = walk ? Math.abs(Math.sin(phase)) * 14 : Math.sin(t * 2.4 + seed) * 3;
      const lean = walk ? 4 : 0;
      const j = boil(seed, t);
      bb.redraw((ctx) => {
        ctx.save();
        ctx.translate(300, 0);
        ctx.rotate((lean * Math.PI) / 180 * 0.2);
        const cx = 0, hw = 316, hh = 300, top = 22 - bob, neck = top + hh - 12, hip = neck + 280;
        // legs
        const sw = walk ? Math.sin(phase) * 26 : 0;
        for (const s of [-1, 1]) {
          const fx = cx + s * 46 + Math.sin((sw * s * Math.PI) / 180) * 160;
          limb(ctx, cx + s * 44, hip - 10, fx, SOLE - 24 + (walk && Math.sin(phase) * s > 0 ? -10 : 0), 38, pants);
          ctx.beginPath(); ctx.ellipse(fx + 20, SOLE - 18, 46, 22, 0, 0, Math.PI * 2);
          ctx.fillStyle = shoes; ctx.fill(); stroke(ctx, 7);
        }
        // torso: a soft trapezoid
        ctx.beginPath();
        ctx.moveTo(cx - 88 + j(), neck + 14); ctx.quadraticCurveTo(cx, neck - 10, cx + 88 + j(), neck + 14);
        ctx.quadraticCurveTo(cx + 112, neck + 120, cx + 104 + j(), hip + 6);
        ctx.quadraticCurveTo(cx, hip + 30, cx - 104 + j(), hip + 6);
        ctx.quadraticCurveTo(cx - 112, neck + 120, cx - 88 + j(), neck + 14); ctx.closePath();
        ctx.fillStyle = shirt; ctx.fill(); ctx.lineJoin = "round"; stroke(ctx, 9);
        // arms
        const arms = p.arms || ["down", "down"];
        const swing = walk ? Math.sin(phase) * 22 : 0;
        const pl = Array.isArray(arms[0]) ? arms[0] : (arms[0] === "down" ? [ARM.down[0] + swing, ARM.down[1]] : arms[0]);
        const pr = Array.isArray(arms[1]) ? arms[1] : (arms[1] === "down" ? [ARM.down[0] - swing, ARM.down[1]] : arms[1]);
        self.hands = [arm(ctx, -1, cx - 84, neck + 34, pl, t, shirt, skin), arm(ctx, 1, cx + 84, neck + 34, pr, t, shirt, skin)];
        // head: a bean, wider at the temples, a narrower chin, the crown slightly pointed
        const hcx = cx, hcy = top + hh / 2;
        ctx.beginPath();
        ctx.moveTo(hcx + j(), top + j());
        ctx.bezierCurveTo(hcx + hw * 0.62, top + j(), hcx + hw * 0.56, top + hh * 0.78, hcx + j(), top + hh);
        ctx.bezierCurveTo(hcx - hw * 0.56, top + hh * 0.78, hcx - hw * 0.62, top + j(), hcx + j(), top);
        ctx.fillStyle = skin; ctx.fill(); stroke(ctx, 10);
        hair(ctx, style, hcx, top, hw, hh, hairColor, j);
        face(ctx, hcx, hcy + hh * 0.08, hw, p.mood || "neutral", t, !!p.talk, blinks, j);
        ctx.restore();
      });
      return self;
    },
  };
  self.group.position.set(opts.x || 0, 0, opts.z || 0);
  return self;
}

/**
 * Iro, the app's mascot: a small round robot penguin. Glossy black and gold armour, big round eyes,
 * a glowing orange core on its chest. About 0.9 m tall next to a person. Never a human.
 * iro.pose(t, { x, z, mood: "happy" | "neutral" | "proud", wave: true, hop: metres, glow: 0..1 }).
 */
export function iro(S, opts = {}) {
  const heightM = opts.height || 0.9;
  const bb = card(S, null, heightM, "iro");
  const br = rng(hash("iro"));
  const blinks = []; for (let t = 0.6 + br(); t < 120; t += 0.8 + br() * 1.8) blinks.push(t);
  const self = {
    card: bb, group: bb.group,
    pose(t, p = {}) {
      bb.group.position.set(p.x ?? self.group.position.x, p.hop || 0, p.z ?? self.group.position.z);
      const bob = Math.sin(t * 3.1) * 6, j = boil(77, t);
      const glow = p.glow ?? (0.75 + Math.sin(t * 4) * 0.25);
      bb.redraw((ctx) => {
        const cx = 300, top = 120 - bob, w = 420, h = 840;
        // feet
        ctx.fillStyle = "#f29a2e";
        for (const s of [-1, 1]) { ctx.beginPath(); ctx.ellipse(cx + s * 80, SOLE - 24, 70, 28, 0, 0, Math.PI * 2); ctx.fill(); stroke(ctx, 8); }
        // flippers
        for (const s of [-1, 1]) {
          const up = p.wave && s > 0 ? -60 + Math.sin(t * 12) * 20 : 30;
          ctx.save(); ctx.translate(cx + s * (w * 0.47), top + h * 0.45); ctx.rotate(((s * up) * Math.PI) / 180);
          ctx.beginPath(); ctx.ellipse(s * 20, 70, 42, 120, s * 0.15, 0, Math.PI * 2);
          ctx.fillStyle = "#16181c"; ctx.fill(); stroke(ctx, 8);
          ctx.beginPath(); ctx.ellipse(s * 20, 110, 28, 60, s * 0.15, 0, Math.PI * 2); ctx.fillStyle = "#c99a3a"; ctx.fill();
          ctx.restore();
        }
        // body: a round black egg with a gold rim and a pale belly
        ctx.beginPath(); ctx.ellipse(cx + j(), top + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
        const gr = ctx.createLinearGradient(cx - w / 2, top, cx + w / 2, top + h);
        gr.addColorStop(0, "#3a3d44"); gr.addColorStop(0.45, "#16181c"); gr.addColorStop(1, "#08090b");
        ctx.fillStyle = gr; ctx.fill(); stroke(ctx, 11);
        ctx.beginPath(); ctx.ellipse(cx, top + h * 0.62, w * 0.34, h * 0.3, 0, 0, Math.PI * 2);
        ctx.fillStyle = "#e9e1cf"; ctx.fill(); ctx.lineWidth = 10; ctx.strokeStyle = "#c99a3a"; ctx.stroke();
        // the glowing core
        const core = ctx.createRadialGradient(cx, top + h * 0.6, 4, cx, top + h * 0.6, 70);
        core.addColorStop(0, "#fff3c9"); core.addColorStop(0.35, "#ffb547"); core.addColorStop(1, "rgba(255,120,30,0)");
        ctx.globalAlpha = 0.6 + glow * 0.4; ctx.fillStyle = core;
        ctx.beginPath(); ctx.arc(cx, top + h * 0.6, 70, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
        ctx.beginPath(); ctx.arc(cx, top + h * 0.6, 30, 0, Math.PI * 2); ctx.fillStyle = "#ff8a2a"; ctx.fill(); stroke(ctx, 7, "#7a3b10");
        // eyes: two big round eyes in gold rims
        const blink = blinks.some((b) => t >= b && t < b + 0.12);
        for (const s of [-1, 1]) {
          const ex = cx + s * 84, ey = top + h * 0.24;
          ctx.beginPath(); ctx.arc(ex, ey, 62, 0, Math.PI * 2); ctx.fillStyle = "#c99a3a"; ctx.fill(); stroke(ctx, 8);
          ctx.beginPath(); ctx.arc(ex, ey, 48, 0, Math.PI * 2); ctx.fillStyle = "#fbf7ee"; ctx.fill();
          if (blink) { ctx.beginPath(); ctx.moveTo(ex - 34, ey); ctx.lineTo(ex + 34, ey); stroke(ctx, 9); }
          else {
            ctx.beginPath(); ctx.arc(ex + 6, ey + 4, 24, 0, Math.PI * 2); ctx.fillStyle = "#101114"; ctx.fill();
            ctx.beginPath(); ctx.arc(ex + 14, ey - 6, 8, 0, Math.PI * 2); ctx.fillStyle = "#ffffff"; ctx.fill();
          }
        }
        // beak
        ctx.beginPath(); ctx.moveTo(cx - 34, top + h * 0.36); ctx.lineTo(cx + 34, top + h * 0.36);
        ctx.lineTo(cx, top + h * 0.36 + (p.mood === "happy" || p.mood === "proud" ? 46 : 36)); ctx.closePath();
        ctx.fillStyle = "#f29a2e"; ctx.fill(); stroke(ctx, 7);
      });
      return self;
    },
  };
  self.group.position.set(opts.x || 0, 0, opts.z || 0);
  return self;
}

/** A flat effect card in the world (a puff, a heart, a star): draw(ctx, t) on a 600 x 1000 canvas. */
export function effect(S, opts = {}) {
  const bb = card(S, null, opts.height || 1, opts.name || "effect");
  bb.group.children[0].visible = false;                      // no contact shadow
  bb.group.position.set(opts.x || 0, opts.y || 0, opts.z || 0);
  return {
    card: bb, group: bb.group,
    draw(t, fn) { bb.redraw((ctx) => fn(ctx, t)); return this; },
  };
}

const module = { THREE, rng, hash, clamp, lerp, glide, pop, LIGHTS, PAINT, SKIN, stage, mat, flat, ink, box, ground,
  street, house, tree, lamp, clouds, screen, loadTexture, cameraPath, person, iro, effect };
export default module;
