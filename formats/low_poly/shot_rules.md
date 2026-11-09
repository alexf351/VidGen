THE LOOK: Low Poly
Clean geometric toys. Every surface is a flat triangle catching the light.
- Flat shading on everything with very few faces, hard directional light plus a colored rim light.
  The background is flat-shaded triangles in a gradient. Rocks, trees and planets are faceted.
- What breaks it: smooth shading, or so many faces it stops looking low poly.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, setting, lighting, then for every character in the shot their identity
  sentence word for word followed by their outfit, and what they are doing. Vertical
  composition with ONE big thing in the middle: people need to get each shot in under a second,
  often on a phone with the sound off. No text in the image.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of camera and subject motion for a short clip. Slow rotation of the subject so the faces flash as they catch the light.
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
