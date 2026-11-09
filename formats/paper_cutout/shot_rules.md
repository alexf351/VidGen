THE LOOK: Paper Cutout
Layers of cut card on a little stage, like a kids' pop-up book.
- Flat color shapes, each with a small soft shadow so the layers lift off each other. The sky is
  torn strips of paper, clouds in layers, stars hang on threads, paper fiber over everything.
- Characters have arms on split-pin joints. Smoke and fire are paper too.
- What breaks it: big blurry shadows, gradients inside a shape, or smooth motion.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, setting, lighting, then for every character in the shot their identity
  sentence word for word followed by their outfit, and what they are doing. Vertical
  composition with ONE big thing in the middle: people need to get each shot in under a second,
  often on a phone with the sound off. No text in the image.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of camera and subject motion for a short clip. Stop-motion at 8 poses a second: paper layers sliding at different speeds, arms swinging from their joints.
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
