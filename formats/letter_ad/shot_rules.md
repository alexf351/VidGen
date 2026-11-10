THE BACKGROUND
{{STYLE}}
- The letter sits on a paper card in the middle of the screen; the photo shows around it. Pick
  quiet, everyday backgrounds that match the mood of the line: a desk at night, a train window,
  a coffee going cold, a laptop in the dark, a sunny window. No faces needed, no text.

SHOT FIELDS
- "image_prompt" must begin with this exact style line, then a comma, then the scene:
  "{{STYLE}}"
- The first shot always describes its background. After that, a shot may set "image_prompt": ""
  and "motion_prompt": "" to keep the previous background (the letter keeps building on the same
  photo). Change the background two or three times in the whole video, when the mood turns.
- "motion_prompt" is a short camera note ("slow push-in"); the shot stays a still.
- "characters" lists anyone visible (usually []).
- "animate" is false on every shot.

THE APP ON SCREEN
- The image model must never draw the app. Whenever someone uses or holds up their phone, the
  image_prompt shows the BACK of the phone toward the camera. Never describe the app's UI, what a
  phone screen shows, menus, buttons, logos or the words "Iro AI" in any image_prompt.

{{APP_SCREENS}}
