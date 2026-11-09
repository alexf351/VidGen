# Viral video skills for Claude

Two Claude skills:

| Folder | What it does |
|---|---|
| `viral-video-writing/` | Writes the script. Hook rules, storytelling, anti-AI writing rules, engagement checks, the tools to use, and a checker. Claude drafts, scores and rewrites until it passes. |
| `famous-reel-editor/` | Edits the video. Turns one raw talking-head clip into a finished 9:16 reel: clean cuts, silences trimmed, animated graphics, one-word captions, music. Built by Riccardo (Martes AI). |

Write with the first one, film it, edit with the second one.

## Install (Claude Code)
1. Unzip.
2. Move both folders into `~/.claude/skills/`:
   ```bash
   mv viral-video-writing famous-reel-editor ~/.claude/skills/
   ```
3. Set up the editor once: open Claude Code and paste the first prompt in `famous-reel-editor/INSTALL-PROMPT.md`. It checks what you need (ffmpeg, Node, Python) and asks before installing anything.

## Install (Claude.ai)
Settings → Capabilities → Skills → upload `viral-video-writing` as a zip. The editor needs a computer to run ffmpeg, so use it in Claude Code.

## Use it
- "Write me a reel about how I got my first client." (writing)
- "Why did this video flop?" + the transcript (writing)
- "Make a vertical reel from ~/Desktop/my-clip.mov" (editor)

## Two things to know
- **Transcription for the editor:** use your own ElevenLabs API key (best timing) or the free local Whisper. `famous-reel-editor/SETUP.md` covers both.
- **Music:** the editor's default track is a placeholder. Swap in your own licensed track before you post.
