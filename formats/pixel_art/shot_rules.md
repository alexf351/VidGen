THE LOOK: Pixel Art
A tiny old game world. Every shape is made of big square pixels.
- Every shape is built from big square pixels: a small palette, 3 or 4 shades per color, flat sky
  bands with a checker dither where they meet, a dark 1-pixel outline on the subject.
- Round things (a moon, a starburst) are stepped pixel circles.
- What breaks it: smoothing, soft gradients, or a sprite with too many colors.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, setting, lighting, then for every character in the shot their identity
  sentence word for word followed by their outfit, and what they are doing. Vertical
  composition with ONE big thing in the middle: people need to get each shot in under a second,
  often on a phone with the sound off. Text only as a tiny blocky pixel-font game HUD of at most two words (a score, "LEVEL 1"); no other text.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of camera and subject motion for a short clip. Simple game motion: a sprite hopping or walking, a scrolling background, no smooth camera moves.
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
