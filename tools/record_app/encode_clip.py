"""frames -> assets/screens/<name>.mp4 (860x1864, 30 fps, H.264, no sound) with the iOS status bar on top.
   encode_clip.py <frames dir> <out.mp4> [--start N] [--end N] [--speed X] [--hold SECONDS]"""
import argparse, subprocess, sys
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument("frames"); ap.add_argument("out")
ap.add_argument("--start", type=int, default=0); ap.add_argument("--end", type=int, default=None)
ap.add_argument("--speed", type=float, default=1.0); ap.add_argument("--hold", type=float, default=0.0)
a = ap.parse_args()
frames = sorted(Path(a.frames).glob("f*.jpg")); end = a.end if a.end is not None else len(frames) - 1
n = end - a.start + 1
bar = Path(__file__).parent / "status-bar.png"
vf = f"[0:v]setpts=PTS/{a.speed}"
if a.hold: vf += f",tpad=stop_mode=clone:stop_duration={a.hold}"
vf += ",fps=30[v];[1:v]scale=860:-1[sb];[v][sb]overlay=0:0,format=yuv420p[o]"
cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-start_number", str(a.start), "-i", str(Path(a.frames) / "f%04d.jpg"),
       "-i", str(bar), "-filter_complex", vf, "-map", "[o]", "-frames:v", str(round((n / a.speed + a.hold * 30))),
       "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", a.out]
subprocess.run(cmd, check=True)
dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out], capture_output=True, text=True).stdout.strip()
print(Path(a.out).name, f"{float(dur):.2f}s", Path(a.out).stat().st_size // 1024, "KB")
