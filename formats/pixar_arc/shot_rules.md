        SHOT FIELDS
        - "image_prompt" must begin with this exact style line, then a comma, then the scene:
          "{{STYLE}}"
          After the style line: camera framing, setting, lighting, then for every character in
          the shot the locked identity word for word followed by their outfit for this scene,
          their ACTING (see below), and the counter value when one is in frame. Vertical
          composition. No text in the image except the counter.
        - ACTING. The picture is a frame from the middle of a performance, never a line-up. For
          every character in the shot write two things. Their FACE: a specific expression that
          fits this beat (jaw clenched and eyes wet, a smug half-smile, eyebrows shot up in
          shock, a slow grin spreading, laughing with his head thrown back). Their BODY, caught
          mid-action: stepping back, slumping against a wall, leaning in to point, jumping off a
          chair with both fists up, storming out, dropping to his knees. Never write a character
          standing straight with arms at their sides, posing, or looking blankly at the camera.
          The emotion changes from shot to shot with the story: humiliated, crushed, stubborn,
          exhausted, stunned, euphoric, cool and unbothered. No two shots in a row give the hero
          the same expression and pose.
        - "characters" lists the ids of every character visible in the shot (may be empty).
        - "motion_prompt" directs a 4 second clip made from the picture. Performance first,
          camera second. Start with what each visible character DOES and how their face changes
          during the clip, as actions a director could shoot: "Marcus's smile drops, he staggers
          back a step and the box slips from his hands; Tyler throws his head back laughing and
          slaps the car roof." People move through the space (walk in, turn away, sit down hard,
          jump up, grab, hug, shove a door open) and react to each other. End with ONE camera
          move that follows the action (a fast push-in on his face, a pull-back as he walks off,
          a handheld follow). Two sentences, 20-40 words. Never a camera move alone, and never a
          character who only stands there while the camera drifts.
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
