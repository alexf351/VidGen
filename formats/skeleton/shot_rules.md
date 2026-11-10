THE LOOK
{{STYLE}}
- A photoreal skeleton in real places, shot like a nature documentary: a park path, a desk at
  night, a kitchen, a gym. The contrast between the skeleton and the ordinary setting is the hook.
- The glow (brain, spine, sometimes the hands) is the only effect. Brighter means working, dim
  means idle. Never gore, blood or anything medical-looking.
- Whole body in most shots, a close-up of the skull and glowing brain when the line is about
  thinking.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, what is in the shot and what it is doing, then for every character their
  identity sentence word for word. ONE clear subject in the middle of a vertical frame. No text
  in the image.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of motion for a short clip. Natural body motion: the skeleton walks, slumps, sits up, types. The glow pulses with it.
- "animate" is true for AT MOST {{MAX_ANIMATED}} shots: the ones where the motion IS the
  explanation. The rest are stills with a slow push-in.
- Each shot shows exactly what its line says. If the line says the signal gets blocked, the
  picture shows the signal getting blocked.

THE APP ON SCREEN
- The image model must never draw the app. Whenever someone uses or holds up their phone, the
  image_prompt shows the BACK of the phone toward the camera. Never describe the app's UI, what a
  phone screen shows, menus, buttons, logos or the words "Iro AI" in any image_prompt.
{{APP_SCREENS}}
