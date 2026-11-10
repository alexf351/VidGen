THE LOOK
{{STYLE}}
- A 3D animated feature: expressive characters, big readable poses, warm light. Each shot is the
  picture of its lyric line, one big thing in the middle of a vertical frame.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, setting, lighting, then for every character in the shot their identity
  sentence word for word followed by their outfit, and what they are doing. No text in the image.
- "characters" lists the ids of every character visible in the shot.
- "motion_prompt" is one sentence of motion for a short clip: on the beat, bouncy, dance-like.
- "animate" is true for AT MOST {{MAX_ANIMATED}} shots: the hook, Iro arriving and the payoff.
- Shots are short (each lasts as long as its sung line), so keep each picture simple.

THE APP ON SCREEN
- The image model must never draw the app. Whenever someone uses or holds up their phone, the
  image_prompt shows the BACK of the phone toward the camera. Never describe the app's UI, what a
  phone screen shows, menus, buttons, logos or the words "Iro AI" in any image_prompt.

{{APP_SCREENS}}
