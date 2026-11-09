// Plays story.json: each beat is drawn by its own file in styles/, and the styles change on a hard cut.
import * as THREE from 'three'
const FORMATS = { vertical: { W: 966, H: 1716, px: [1080, 1920] }, wide: { W: 3051, H: 1716, px: [1920, 1080] } }

const start = async () => {
  const story = await (await fetch('story.json')).json()
  let words = []
  try { words = (await (await fetch('voice.json')).json()).words || [] } catch {}
  const F = FORMATS[story.format || 'vertical']
  if (!F) throw new Error('format must be vertical or wide')
  const out = document.getElementById('out'); out.width = F.W; out.height = F.H
  out.style.width = F.px[0] + 'px'; out.style.height = F.px[1] + 'px'
  await Promise.all(['italic 800 56px "Inter Tight"', '400 60px Bangers'].map((f) => document.fonts.load(f).catch(() => {})))
  await document.fonts.ready

  const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' })
  renderer.setPixelRatio(1)
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  renderer.outputColorSpace = THREE.SRGBColorSpace

  // A style can appear more than once, so each beat gets its own copy.
  let t = 0
  const beats = []
  for (const [index, b] of story.beats.entries()) {
    const mod = (await import(`./styles/${b.style}.js`)).default
    const s = Object.create(mod)
    await s.create({ W: F.W, H: F.H, THREE, renderer, words, start: t, end: t + b.seconds, index, line: b.line, beat: b })
    beats.push({ s, start: t, end: t + b.seconds })
    t += b.seconds
  }
  window.DUR = t
  window.SIZE = F.px
  const o = out.getContext('2d')
  window.seek = (time) => {
    let i = beats.findIndex((b) => time < b.end); if (i < 0) i = beats.length - 1
    const b = beats[i]
    o.setTransform(1, 0, 0, 1, 0, 0); o.globalAlpha = 1; o.shadowColor = 'transparent'
    b.s.render(time - b.start, o, b.end - b.start)
  }
  window.seek(0)
  window.READY = true
}
start().catch((e) => { console.error(e); window.FAILED = String((e && e.stack) || e) })
