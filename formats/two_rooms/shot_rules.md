THE LOOK: Two Rooms
A painted cutaway, seen straight from the front like a dollhouse with the front wall taken off.
- The two-room picture: the frame is split into two rooms of the same size, one above the
  other, with a thick floor between them at the exact middle of the picture. Both rooms have
  the SAME layout and the same furniture, in the same places. What differs is the person, what
  they are doing, and how the room is lit: the room of the one who does the work is warm and
  lit by a lamp, the other room is dimmer and the coldest light in it is a phone on a face.
- One thing in the working room shows time passing and effort adding up, and the clip can fill
  it in: a board that fills with notes, a shelf that fills with books, a wall of sketches, a
  row of trophies. The other room has the same thing, empty, and it stays empty.
- The shared moment (the middle shot) is one wide picture with both of them side by side, in a
  bright place, each reacting in their own way to the same news.
- What breaks it: a camera that moves around, rooms that are not alike, more than the two
  people in the rooms, or any writing in the picture.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
  After that: the framing, the place, the light, then for each of the two people their identity
  sentence word for word followed by their clothes ("in a pale blue shirt") and what they are
  doing. Say which room each one is in (upstairs, downstairs) or which side they are on (left,
  right), and keep that for the whole video. Each keeps the same clothes in every shot, in the
  same words. No text in the image.
- "characters" lists both ids on every shot.
- "motion_prompt" describes the whole clip, which runs as long as the shot's "seconds" (8 to
  12 seconds, not 4). Say what each of the two does over that time, one after the other, and
  what changes in the picture by the end (the board fills up, the box gets packed, the light in
  one room goes out). Say what does NOT move as well: the camera stays still on the two-room
  shots.
- "animate" is true on every shot.
- "seconds" is how long the shot runs: 8 to 12. The three shots together run 26 to 32 seconds.
- "scene": "rooms" goes on every two-room shot. The later ones are then drawn from the first
  one's picture, so the house stays the same house. Describe the rooms in the SAME words each
  time and change only what the story changed (the time of day, a box on the floor, the full
  board).
- "captions" is the list of lines for that shot. Each is {"text": "...", "at": <seconds into
  the shot>}. Add "to" when a line should go before the next one comes (a pause with no text
  before the last line makes it land), and "y" to move a line: 0.5 is the floor between the two
  rooms (the default), 0.12 is near the top (use it on the middle shot), 0.25 is inside the
  upper room (use it for the closing question when that room has gone dark).
