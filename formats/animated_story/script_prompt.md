# Animated Story: the rules for this format

A 20 to 30 second narrated story ad for the Iro AI app, for Reels and TikTok, in one look: flat 2D
cartoon people (bean heads, stick limbs, dark plum outlines) in a colourful painted 3D town drawn
with thick black ink lines under a deep blue sky. One narrator tells it; VidGen puts the captions
on. Every picture is drawn in code with `assets/lib/toon.js` (read looks/toon.md).

## What Iro is (claim nothing else)

A mobile app that teaches AI in about 5 minutes a day, like a language app: learning paths of
short lessons, Iro the robot penguin as your coach, XP, ranks, streaks, a Prompt Lab that scores
your prompts out of 10, Ask Iro (a chat coach). The search term is "Iro AI".

## The story (story.json)

One beat per line, 7 to 11 beats, every beat's `style` is `toon`. The shape: someone wants
something -> they try and it goes wrong in a way you can see -> they open Iro -> one result you
could draw -> the payoff -> a twist that pays off the first lines -> the last line is exactly
"Search Iro AI".

- Lines of 3 to 9 words, said by one narrator in one steady tone. About 3.5 words a second.
- Every line is something that happens on screen. Never describe what the picture already shows.
- Iro appears from the turn on, as a small robot penguin beside the hero, never a human and never
  talking: the narrator speaks.
- The app's result is shown on a phone with a REAL screen from assets/screens/ (by file name).
- The last beat: the hero and Iro in the street, the sun gone golden, while the narrator says
  "Search Iro AI".

In story.md, for every beat: where it is (one town, the same street and houses in every beat),
who is in it, what they do, their mood, the camera (wide, medium or close, and its move).

## The scenes

Read looks/toon.md and the worked example `examples/compositions/toon_beat.html`, and keep a cast
table in plan.md (every character's options) so each person is identical in every beat. Build the
same town in every beat (same house seeds and colours) and move the camera, not the town.
