THE LOOK: Retro Anime
An 80s TV anime on film. Big drama in simple cels.
- A painted gradient sky (deep blue to magenta to peach), a huge striped sun disc behind the
  subject, flat color with one shadow tone and thin dark lines, sparkles and film grain.
- Draw the subject large in the frame and from a low angle.
- Save the impact for one moment: speed lines and a shock ring on the turn, once.
- What breaks it: soft 3D-looking shading, or impact frames on every shot.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, setting, lighting, then for every character in the shot their identity
  sentence word for word followed by their outfit, and what they are doing. Vertical
  composition with ONE big thing in the middle: people need to get each shot in under a second,
  often on a phone with the sound off. No text in the image.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of camera and subject motion for a short clip. Dramatic: a push-in on the subject, and on the one big moment a burst of speed lines.
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
