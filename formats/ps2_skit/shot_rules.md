THE LOOK: a PS2 cutscene
A cutscene from a 2004 console game. Blocky people with flat painted faces, blurry ground, one
room in two or three bold colours.
- 3D with very few sides per shape, small noisy textures, simple lighting, no real shadows (a
  dark blob under each character instead), fog or darkness at the edges of the room, faint
  scanlines over the frame.
- What breaks it: high-res textures, soft shadows, smooth skin, too many polygons.
- No words anywhere in a picture: no HUD text, no subtitles, no signs, no menus. The subtitles
  and the hook tag are added afterwards.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: framing, the room (in the SAME words in every shot: it is one room), lighting,
  then for every character in the shot their identity sentence word for word followed by their
  outfit, where they are in the frame (left, right, middle) and what they are doing with their
  face and hands. Vertical composition with ONE face or ONE thing big in the middle.
- Framing is rude and close, the way those cutscenes were cut: a face filling the frame, a
  low angle up at the judge, a two shot across the table, a hand slamming down. One wide shot
  of the room at most. The shock beat is an extreme close-up: eyes and brow only.
- Who stands where never changes: if the judge is on the left of the table in one shot, he is
  on the left in every shot that shows both sides. Say the side in every such shot.
- "characters" lists the ids of every character visible in the shot (may be empty).
- "same_scene": true on every shot after the first that has an image_prompt (it is one room:
  the pictures are then drawn from the first shot, so the room and the clothes stay the same).
  Leave it off the first shot.
- "animate" is true on every shot that has an image_prompt. "motion_prompt" is one or two
  sentences: what the speaker's face and hands do while the line is said (stiff, a little
  puppet-like, the way game characters moved: a slow head turn, one blink, a hand that lifts
  and drops), then one camera move (a slow push in, a snap zoom on the shock beat, a slow swing
  around the table). End the motion_prompt of every spoken shot with: "Flat deadpan delivery,
  like a 2000s game cutscene voice." Nobody walks out of frame, nothing explodes.
- A spoken shot shows its speaker's face clearly, mouth visible.

THE APP ON SCREEN
- The image model must never draw the app. Whenever a character holds the phone, the
  image_prompt shows the BACK of the phone toward the camera, with the screen's glow on their
  face. Never describe the app's UI, what a phone screen shows, menus, buttons, logos or the
  words "Iro AI" in any image_prompt.
{{APP_SCREENS}}
