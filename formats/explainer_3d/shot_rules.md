THE LOOK
{{STYLE}}
- Every shot looks like a frame from a polished 3D animation: one realistic 3D character or
  object, lit cleanly, floating in front of a plain bright background (teal, sky blue, soft
  yellow). No rooms unless the line needs one.
- Show the inside of things: cross-sections of a head or a phone, x-ray views, arrows of light,
  tiny workers, gears. The metaphor must be readable in one second with the sound off.
- Faces are a little exaggerated (sweat, wide eyes, a smug grin), never scary or gory.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, what is in the shot and what it is doing, then for every character their
  identity sentence word for word. ONE clear subject in the middle of a vertical frame. No text
  in the image.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of motion for a short clip. Simple and literal: the thing in the line happens (it fills up, it shrinks, it lights up), with a slow camera move.
- "animate" is true for AT MOST {{MAX_ANIMATED}} shots: the ones where the motion IS the
  explanation. The rest are stills with a slow push-in.
- Each shot shows exactly what its line says. If the line says the signal gets blocked, the
  picture shows the signal getting blocked.

THE APP ON SCREEN
- The image model must never draw the app. Whenever someone uses or holds up their phone, the
  image_prompt shows the BACK of the phone toward the camera. Never describe the app's UI, what a
  phone screen shows, menus, buttons, logos or the words "Iro AI" in any image_prompt.
{{APP_SCREENS}}
