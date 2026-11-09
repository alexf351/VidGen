# The 10 styles

For each one: how it looks, the rules that make it read as that style, what to change for a new subject, and the mistake that breaks it.

## 1. Pixel art (`pixel.js`)

A tiny old game world. Every shape is made of big square pixels.

- **Rules:** draw on a canvas about 120 pixels wide (vertical) and scale it up with smoothing off. Use a small palette, 3 or 4 shades per color. Skies are flat bands with a checker dither where they meet. Add a dark 1-pixel outline on the subject. Text comes from the bitmap font at the top of the file (capitals, digits, common marks), never a real font.
- **New subject:** plot it pixel by pixel with `px(x, y)`. Round shapes work with a distance test, as the moon and the starburst do. Swap the HUD words.
- **Breaks it:** smoothing, soft gradients, or a sprite with too many colors.

## 2. PS2 style (`ps2.js`)

A cutscene from a 2003 game. Blocky people, blurry ground, a sky that doesn't quite join up.

- **Rules:** 3D with very few sides per shape (`seg: 6`), small nearest-neighbour textures (16 to 32 pixels) full of noise, simple lighting, no real shadows (a dark blob under the character instead), fog in the distance. Render at about 300 by 536, stretch it up with smoothing on, and lay faint scanlines over it. Bold italic HUD on top, with a mission line and a bar.
- **New subject:** build it with the `kit` and swap the mission text. Swinging the camera slowly around the subject sells the game feel.
- **Breaks it:** high-res textures, soft shadows, or too many polygons.

## 3. Comic art (`comic.js`)

A page from a comic book. Loud, flat and inked.

- **Rules:** every piece gets a thick black outline underneath, then flat color. Ben-Day dots over the background and a darker dot pattern for shade. Radial action lines burst from the subject. Yellow caption boxes, and giant lettering in the Bangers font with a thick outline. Shake the camera on the hit, and a black frame around the panel.
- **New subject:** draw it through `paint`. Change the caption and the sound word (BOOM, CRASH, DING) to match the moment.
- **Breaks it:** gradients, thin lines, or lettering without an outline.

## 4. Lego style (`brick.js`)

The whole world built from toy bricks, including the sky.

- **Rules:** every object is stacked bricks with visible seams and round studs on top. Rows are staggered like real walls. Plastic material with low roughness, an environment map, and one soft sun with shadows. The sky is a blue baseplate full of studs. Use instanced meshes, or it gets slow.
- **New subject:** build it from `addH` bricks, with hard corners. Curves become steps. Cartoon plastic only, no real toy brand logos on studs or boxes.
- **Breaks it:** smooth surfaces, missing studs, or perfectly aligned rows.

## 5. Claymation (`clay.js`)

Hand-sculpted plasticine under a soft studio light, animated by hand.

- **Rules:** chunky rounded shapes (spheres, capsules, lathes). A bump map of thumbprints with a strong bump scale, a soft key light with blurred shadows, a pale plain background. Animate at 12 poses a second, with a tiny random nudge on every pose, and shift the bump map a little each pose so the surface boils.
- **New subject:** build it from fat rounded parts. Round everything more than feels right. Flames, water and smoke are solid clay blobs too.
- **Breaks it:** smooth motion at 30 frames a second, or thin parts.

## 6. Paper cutout (`paper.js`)

Layers of cut card on a little stage, like a kids' pop-up book.

- **Rules:** flat color shapes, each with a small soft shadow, so the layers lift off each other. The sky is torn strips of paper. Clouds in 3 layers slide at different speeds. Stars hang on threads. Lay paper fiber over the whole frame. Move at 8 poses a second, and arms swing from the joints like split pins.
- **New subject:** draw it through `paint`. Keep shapes simple with clean cut edges. Smoke and fire are paper too.
- **Breaks it:** big blurry shadows, gradients inside a shape, or smooth motion.

## 7. Retro anime (`anime.js`)

An 80s TV anime on film. Big drama in simple cels.

- **Rules:** a painted gradient sky (deep blue to magenta to peach), a huge striped sun disc behind the subject, flat color with one shadow tone and thin dark lines. Animate on twos. On the big moment, 2 inverted frames, then a burst of speed lines and a shock ring. Sparkles and film grain to finish.
- **New subject:** draw it through `paint`, large in the frame and from a low angle. Save the impact frame for one moment per beat.
- **Breaks it:** using the inverted frames more than once, or soft 3D-looking shading.

## 8. Low poly 3D (`poly.js`)

Clean geometric toys. Every surface is a flat triangle catching the light.

- **Rules:** `flatShading: true` on everything, with very few faces. Hard directional light plus a colored rim light. The background is flat-shaded triangles in a gradient. Icosahedrons with their corners pushed in or out make rocks, trees and planets.
- **New subject:** build it with a small `seg` in the `kit`. Rotate things slowly so the faces flash as they catch the light.
- **Breaks it:** smooth normals, or so many faces it stops looking low poly.

## 9. Risograph (`riso.js`)

A print from a small art press. Two inks, visible dots, nothing lined up quite right.

- **Rules:** paint the picture twice, once for each ink, as a density map from 0 to 1. Each ink gets its own halftone screen at a different angle. Add grain, and print the second ink a few pixels off so the colors overlap at the edges. Inks multiply on off-white paper, so orange over blue makes a third dark color. Animate at 12 poses a second and re-seed the grain each pose.
- **New subject:** give each piece a tone in `toneA` and `toneB`. Try other ink pairs: pink and teal, or yellow and navy.
- **Breaks it:** a third ink, smooth gradients with no dots, or perfect registration.

## 10. Miniature diorama (`mini.js`)

A tiny handmade model on a real desk, shot up close. The reveal style.

- **Rules:** real-looking materials at small scale: cardboard with windows, cotton clouds on wire, a wooden peg. A warm lamp with soft shadows. Tilt-shift blur that gets stronger towards the top and bottom of the frame. Put an everyday object in shot, a mug or a pencil, because that's what gives the scale away.
- **New subject:** build the set around the subject, then pull the camera back from close-up to wide so the viewer finds out it's small.
- **Breaks it:** no everyday object in shot, or blur across the whole frame.
