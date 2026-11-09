        SHOT FIELDS
        - "image_prompt" must begin with this exact style line, then a comma, then the scene:
          "{{STYLE}}"
          After the style line: camera framing, setting, lighting, then for every character in
          the shot the locked identity word for word followed by their outfit for this scene,
          what they are doing, and the counter value when one is in frame. Vertical
          composition. No text in the image except the counter.
        - "characters" lists the ids of every character visible in the shot (may be empty).
        - "motion_prompt" is one sentence of camera and subject motion for a 3-5 second clip.
          Keep it short even for still shots (a slow push-in or drift is fine).
        - "vo_line" is a line of dialogue spoken by one of the cast: {{SPEAKERS}}.
          There is NO narrator: no voice-over that describes events, explains the story or
          talks about the hero in the third person. Every spoken line is a character talking.
          Shots with no dialogue have "vo_line": "" and let the visual carry the beat; MOST
          shots should be silent. Spoken lines are short, usually 2-8 words. The TOTAL word
          count of all vo_lines across the script must be {{VO_WORDS_MIN}}-{{VO_WORDS_MAX}} words.
          Count before you answer.
        - "speaker" is the id of the character who speaks the vo_line (one of {{SPEAKERS}}),
          or "" when vo_line is "". Never "narrator".
        - "caption" is "" or ONE OR TWO WORDS IN ALL CAPS that hit the beat ("LOSER", "DAY 1",
          "DIAMOND", "I'M GOOD"). The only three-word caption allowed is "{{CTA_CAPTION}}" on the
          last shot.
        - "animate" is true for AT MOST {{MAX_ANIMATED}} shots. Reserve it for shots where motion
          IS the beat: a car pulling away, someone walking out, a crowd, a thrown phone, the
          counter climbing, a door slamming. Dialogue close-ups and establishing shots stay false.

        THE APP ON SCREEN
        - The image model must never draw the app. Whenever a character uses the app (or any
          phone), the image_prompt shows the BACK of the phone toward the camera, with the
          screen's glow lighting their face. Never describe the app's UI, what a phone screen
          shows, menus, buttons, logos or the words "Iro AI" in any image_prompt.
{{APP_SCREENS}}
