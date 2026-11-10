- The real app appears in exactly one app screen shot (at most {{APP_SCREENS_MAX}}), right after the narrator brings up Iro.
  It puts a real screenshot in a phone mockup. Pick the screenshot whose content fits the moment,
  using its exact path:
{{SCREEN_LIST}}
- An app screen shot has "app_screen": "<path>", "characters": [], "image_prompt": "",
  "motion_prompt": "", "vo_line": "", "speaker": "", "caption": "", "animate": false. It is
  silent, it is never the first or last shot, and it counts toward the shot total.
