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
        - "vo_line" is either NARRATION or one line of DIALOGUE. A shot carries one or the
          other, never both.
          NARRATION ("speaker": "narrator") is a storyteller's voice over the pictures: third
          person, past tense, short punchy sentences of 4-10 words. "Marcus got dumped for a
          guy with a rented Lambo." "So he made a bet. Thirty days." "By day ten, he wanted to
          quit." The narrator tells the viewer what the pictures cannot: who these people are,
          what just happened, what is at stake, how much time passed, what changed. Someone who
          only LISTENS to the narration must be able to follow the whole story, start to end.
          The narrator never describes what is plainly on screen, never explains the app's
          features and never comments on the story ("little did he know").
          DIALOGUE ("speaker": a character id, one of {{SPEAKERS}}) is for the moments that
          hit hardest when a person says them: the insult, the firing, the bet, the mentor's
          push, the ex asking to come back, the hero's answer. 2-8 words each. At least
          {{DIALOGUE_MIN}} lines are dialogue.
          Narration carries about two thirds of the words and runs through most story shots,
          so the viewer is never lost. A quick reaction shot may be silent ("vo_line": ""), but
          never two silent story shots in a row. The TOTAL word count of all vo_lines across
          the script must be {{VO_WORDS_MIN}}-{{VO_WORDS_MAX}} words. Count before you answer.
        - "speaker" is "narrator" for narration, the id of the character who says a line of
          dialogue (one of {{SPEAKERS}}), or "" when vo_line is "".
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
