THE LOOK
{{STYLE}}
- A clean, realistic 3D world, like a good game cutscene. Bright, saturated, a little filmic.
  A warm sun, blue sky with clouds, soft shadows; night scenes use hard lamps and a dark sky.
  Wide lens up close, depth of field on every shot.
- People: realistic bodies, generic faces, big readable expressions (shock, a smirk, a scream).
  Plain clothes, no logos. Never a real person's likeness, never a real company's
  logo or uniform.
- CALM shots only. Bodies in fast action or contact (running, jumping, fighting, falling) come
  out stiff and broken, so tell the story with frozen moments, hands and objects, rooms,
  vehicles, the sky, top-down views and the aftermath. Never gore.
- Each shot shows exactly what its line says, readable in one second with the sound off.

THE SHOT KIT (pick one per shot, and never the same one twice in a row)
- Macro insert: an extreme close-up of the key object or the hands, very shallow depth of field.
- Hero low angle: a wide lens at waist height, looking up.
- God's-eye top-down: straight down on the scene.
- Over the shoulder: we see what they see.
- Tracked object: the frame follows the thing that matters (the chair, the rope, the phone).
- Glow highlight: the object the line names glows orange with a rim of light.
- A big 3D number lying in the scene, as a solid object, when the line is a number (at most two
  shots; this is the only text allowed in an image).
- A thought bubble: a ring of cloud above the head showing what they hoped for.
- A TV in the scene replaying the event.
- The aftermath: the empty place, the thing left behind.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the shot:
  "{{STYLE}}"
  After that: which shot from the kit, what is in it and the frozen moment it shows, then for
  every character their identity sentence word for word and their outfit (the same every time).
  ONE clear subject in a vertical frame. No text in the image (except a big 3D number shot).
- "characters" lists the ids of every character visible in the shot (may be empty).
- "motion_prompt" is one sentence of CAMERA motion over a nearly still scene: a slow drift, a
  push in, a slow orbit, a slow rotate for a top-down. Small natural motion only (wind, a rope
  swaying, balloons bobbing). Never fast body action.
- "animate" is true for AT MOST {{MAX_ANIMATED}} shots: the first shot, the reveal and the ones
  where something visibly moves. Every other shot is a still with a slow push-in, so nothing
  ever holds still.
- A new picture for every line: a new framing, a new place or a new object. Never two shots in
  a row from the same angle.

{{APP_SCREENS}}
