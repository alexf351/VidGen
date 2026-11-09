# Optional. Reads the "line" of each beat out loud and times the beats to the voice.
#   ELEVENLABS_API_KEY=... python3 voice.py [voice_id]
# Writes voice.mp3 + voice.json, and updates the seconds in story.json.
import base64, json, os, sys, urllib.request
KEY = os.environ.get('ELEVENLABS_API_KEY')
if not KEY: sys.exit('Set ELEVENLABS_API_KEY first. Without a voice, skip this and set the seconds by hand.')
VOICE = sys.argv[1] if len(sys.argv) > 1 else 'UgBBYS2sOqTuMpoF3BR0'
story = json.load(open('story.json'))
lines = [b['line'].strip() for b in story['beats']]
req = urllib.request.Request(f'https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/with-timestamps?output_format=mp3_44100_192',
    data=json.dumps({'text': ' '.join(lines), 'model_id': 'eleven_multilingual_v2', 'voice_settings': {'stability': 0.4, 'similarity_boost': 0.8, 'style': 0.25, 'speed': 1.1}}).encode(),
    headers={'xi-api-key': KEY, 'content-type': 'application/json'})
d = json.load(urllib.request.urlopen(req, timeout=120))
open('voice.mp3', 'wb').write(base64.b64decode(d['audio_base64']))
a = d['alignment']; ch, st = a['characters'], a['character_start_times_seconds']; end = a['character_end_times_seconds'][-1]
starts, i = [], 0
for l in lines: starts.append(st[i]); i += len(l) + 1
for k, b in enumerate(story['beats']):
    b['seconds'] = round((starts[k + 1] if k + 1 < len(lines) else end + 1.2) - starts[k], 2)
story['beats'][0]['seconds'] = round(story['beats'][0]['seconds'] + starts[0], 2)
json.dump(story, open('story.json', 'w'), indent=2)
words, w0 = [], None
for k, c in enumerate(ch + [' ']):
    if c.isspace():
        if w0 is not None: words.append({'w': ''.join(ch[w0:k]).strip('.,!?').lower(), 't': round(st[w0], 3)})
        w0 = None
    elif w0 is None: w0 = k
json.dump({'words': words}, open('voice.json', 'w'), indent=1)
print('Beats timed to voice.mp3. Total', round(end + 1.2, 1), 's')
