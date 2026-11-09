THE LOOK: Comic
A page from a comic book. Loud, flat and inked.
- Every piece has a thick black ink outline and flat color. Ben-Day dots over the background and
  a darker dot pattern for shade. Radial action lines burst from the subject. A black panel frame.
- What breaks it: gradients, thin lines, or lettering without an outline.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, setting, lighting, then for every character in the shot their identity
  sentence word for word followed by their outfit, and what they are doing. Vertical
  composition with ONE big thing in the middle: people need to get each shot in under a second,
  often on a phone with the sound off. On the loud moment, one giant sound word (BOOM, CRASH, DING) in thick outlined comic lettering is allowed; otherwise one yellow caption box of at most four words, or no text.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of camera and subject motion for a short clip. Snappy: a camera shake and speed lines on the hit, otherwise a quick push-in.
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
