THE LOOK: Style Switch
Every shot switches to a different look, on a hard cut. The surprise of it is the transition.
Pick the look for each shot by the moment:
  - the quiet start: pixel art or paper cutout
  - setting a goal: PS2 game
  - the loud moment: comic or retro anime
  - building or growing: brick or claymation
  - things go wrong: paper cutout
  - the turn, the big effort: retro anime
  - obstacles, speed: low poly or PS2 game
  - the win, a poster moment: risograph
  - the reveal: miniature diorama
Fewer looks than shots is fine: repeat them, and try ending in the look you started in.
Keep the subject the same in every look: same silhouette, same two or three colors. That's what
makes a change of look read as the same story instead of a new clip.
The looks (use these exact descriptions):
  - Pixel Art: "16-bit pixel art, big square pixels, small palette with 3 or 4 shades per color, flat sky bands with checker dithering, dark 1-pixel outline on the subject, retro video game scene"
  - PS2 Game: "early 2000s PlayStation 2 era game cutscene, very low-polygon 3D models, small blurry low-resolution textures full of noise, simple lighting, dark blob shadow under characters instead of real shadows, fog in the distance, slightly muddy colors, faint scanlines"
  - Comic: "comic book art, thick black ink outlines on everything, flat bold colors, Ben-Day halftone dots in the background, darker dot pattern for shading, radial action lines bursting from the subject, black panel border"
  - Brick: "everything built from glossy toy plastic building bricks with round studs on top, visible seams between bricks, staggered brick rows, minifigure-style characters, plastic material, one soft sun with soft shadows, sky built from a blue studded baseplate, no brand logos"
  - Claymation: "claymation stop-motion, hand-sculpted plasticine figures and sets, visible thumbprints in the clay, chunky rounded shapes, soft studio key light with soft shadows, pale plain background"
  - Paper Cutout: "paper cutout stop-motion, layers of cut cardstock with small soft shadows lifting them apart, flat colors with clean cut edges, sky of torn paper strips, stars hanging on threads, visible paper fiber texture, pop-up book stage"
  - Retro Anime: "1980s retro TV anime cel, painted gradient sky from deep blue to magenta to peach, huge striped sun disc behind the subject, flat colors with one shadow tone, thin dark lines, sparkles, film grain"
  - Low Poly: "low poly 3D render, flat-shaded triangular faces, very few polygons, nothing round, hard directional light plus a colored rim light, background of flat-shaded triangles in a gradient"
  - Risograph: "risograph print, only two inks, fluorescent orange and blue, on off-white paper, each ink with its own visible halftone dot pattern, grain, the two layers printed slightly out of register, inks overlap into a dark third color"
  - Miniature Diorama: "miniature diorama, a tiny handmade model set on a real wooden desk, cardboard buildings with cut windows, cotton-wool clouds on wire, tiny painted figures, warm desk lamp light with soft shadows, tilt-shift blur stronger toward the top and bottom of the frame, an everyday object like a coffee mug or pencil in shot for scale"

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  Right after the style line, write that shot's look description from THE LOOK list, then a comma.
  After that: framing, setting, lighting, then for every character in the shot their identity
  sentence word for word followed by their outfit, and what they are doing. Vertical
  composition with ONE big thing in the middle: people need to get each shot in under a second,
  often on a phone with the sound off. No text in the image, except the comic look's one sound word on the loud moment.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of camera and subject motion for a short clip. Match the look: stop-motion jitter for claymation and paper, a camera swing for PS2, speed lines for anime.
- "animate" is true for AT MOST {{MAX_ANIMATED}} shots: the loud moment, the turn or the payoff,
  where motion IS the beat. Every other shot stays a still.
- Keep the story moving from shot to shot: if something is climbing at the end of one shot, it's
  still climbing at the start of the next.

THE APP ON SCREEN
- The image model must never draw the app. Whenever a character uses the app (or any phone), the
  image_prompt shows the BACK of the phone toward the camera, with the screen's glow on their
  face. Never describe the app's UI, what a phone screen shows, menus, buttons, logos or the
  words "Iro AI" in any image_prompt.
{{APP_SCREENS}}
