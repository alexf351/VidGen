THE LOOK
{{STYLE}}
- It must look like real phone footage, not an ad: natural light, real rooms, real skin texture,
  slightly imperfect framing, nothing glossy or staged.
- One person per talking shot, facing the camera or the other person, face clearly visible and
  well lit, mouth visible (the shot is lip-synced to the line).

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the shot:
  "{{STYLE}}"
  After that: framing (close-up, medium close-up, waist up), where they are, the light, then for
  the person in the shot their identity sentence word for word followed by their outfit, and
  their expression. Keep each person's outfit and setting the same in every shot. No text in the
  image.
- "characters" lists the ids of everyone visible (a talking shot lists only its speaker).
- "talk": true on a shot where the speaker says their line on camera. The picture becomes a
  lip-synced clip of them saying it, so the image_prompt shows ONLY that person, mouth visible.
  At most {{TALK_MAX}} talking shots.
- "motion_prompt" is one short sentence of how they move while talking (small head movements,
  hand gestures, a glance away, the phone camera shaking a little). Never "smooth" or "cinematic".
- "animate" is false on every shot (talking shots move on their own; the rest are stills).
- "caption" is "" on every shot except the last (spoken words are captioned automatically).

THE APP ON SCREEN
- The image model must never draw the app. Whenever someone uses or holds up their phone, the
  image_prompt shows the BACK of the phone toward the camera. Never describe the app's UI, what a
  phone screen shows, menus, buttons, logos or the words "Iro AI" in any image_prompt.

{{APP_SCREENS}}
