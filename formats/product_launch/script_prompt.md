# Product Launch: the rules for this format

A 15 to 25 second launch film for the Iro AI app, for Instagram Reels, TikTok and X. There is no
narrator: music carries it and the words are on screen, as part of the picture. It shows the real
app (assets/screens/: screenshots and recordings) and never a made-up screen.

## What Iro is (claim nothing else)

A mobile app that teaches AI in about 5 minutes a day, like a language app: learning paths of
short lessons, Iro the robot penguin as your coach, XP, ranks from Bronze to Gold and beyond,
streaks, weekly leagues, reward chests, quests, certificates, duels, a Prompt Lab that scores your
prompts out of 10, Ask Iro (a chat coach), lessons as podcasts, and custom paths on any topic.
The search term is "Iro AI".

## The story (story.json)

One beat per shot, 6 to 10 beats, 15 to 25 seconds in all, each beat 1.5 to 3 seconds (VidGen
moves each beat's end onto the music's nearest beat). Every beat's `style` is `launch`. Its
`line` is the words ON SCREEN in that beat, not a voice:

- At most 5 words. Several beats may have none (`""` is fine when the picture says it).
- About 30 words in the whole film. Small words, a promise you can see.
- The last beat's line is exactly "Search Iro AI", and that beat lasts at least 3 seconds so the
  search term holds 2 seconds once it has landed.

The shape: the hook (already on screen at frame 0: a bold claim or the result) -> the problem in
one line -> the app in hand -> three proof moments, each a real screen doing one thing -> the
payoff -> the end card (the app icon lands, "Iro AI" beside it, then "Search Iro AI").

In story.md, for every beat: the screen or recording it shows (by file name), what the one shape
does, what the cursor clicks or drags, and how the beat hands over to the next one.

## Score the three drafts on these (one point each)

1. Frame 0 is a hook that stops a scroll: a result or a bold claim on screen, never a logo.
2. Every proof beat names a real file from assets/screens/ and shows ONE thing it does.
3. One shape travels through the whole film, and every transition has a cause on screen.
4. No line over 5 words; about 30 words in total; every line says what changes for the viewer.
5. A stranger knows what the app does with the sound off.
6. It ends on the icon, "Iro AI", then "Search Iro AI".

## The scenes

Read looks/launch.md (the look, the motion, the tells to avoid) and skill/launch-shots/README.md,
then pick a shot from its menu for every beat (`skill/launch-shots/shots/...`): name the card in
plan.md beside the beat. Use the recordings for proof moments where you can; a still screen gets
a cursor and a push-in. Never write words into the bottom of the frame below 1330 px.
