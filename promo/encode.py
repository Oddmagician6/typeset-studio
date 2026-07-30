"""Encode the rendered PNG sequence into an MP4 Meta will accept.

    python encode.py                     # frames/ -> typeset-studio-reel-9x16.mp4
    python encode.py --audio track.mp3   # mux a music bed, trimmed to length
    python encode.py --no-silent-track   # omit the silent AAC track

Settings chosen for Instagram / Facebook Reels: H.264 High profile, yuv420p
(anything else shows up as a green or black video on some phones), 30 fps,
+faststart so the file begins playing before it has fully downloaded.

A silent AAC track is added by default. Reels tolerate a video with no audio
stream at all, but some upload paths re-encode or reject it, and a silent track
costs about 1 KB per second.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# must match render_frames.py, which keeps its PNGs out of the OneDrive-synced repo
FRAMES = os.path.join(tempfile.gettempdir(), "typeset-reel-frames")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=FRAMES)
    ap.add_argument("--out", default="typeset-studio-reel-9x16.mp4")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=19, help="lower is better quality")
    ap.add_argument("--audio", default=None, help="music bed to mux in")
    ap.add_argument("--no-silent-track", action="store_true")
    args = ap.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit(
            "ffmpeg is not on PATH.\n"
            "  winget install --id Gyan.FFmpeg -e\n"
            "then open a NEW terminal so PATH picks it up."
        )

    frames = os.path.join(HERE, args.frames)
    pngs = sorted(f for f in os.listdir(frames)) if os.path.isdir(frames) else []
    if not pngs:
        sys.exit(f"no frames in {frames} - run render_frames.py first")
    # the sequence may not start at zero (spot-check renders), so tell ffmpeg
    start_number = int(os.path.splitext(pngs[0])[0].split("_")[1])
    out = os.path.join(HERE, args.out)

    cmd = [ffmpeg, "-y",
           "-framerate", str(args.fps),
           "-start_number", str(start_number),
           "-i", os.path.join(frames, "f_%05d.png")]

    if args.audio:
        cmd += ["-i", os.path.join(HERE, args.audio)]
    elif not args.no_silent_track:
        cmd += ["-f", "lavfi", "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100"]

    cmd += [
        "-c:v", "libx264",
        "-profile:v", "high", "-level", "4.1",
        "-pix_fmt", "yuv420p",
        "-preset", "slow",
        "-crf", str(args.crf),
        "-r", str(args.fps),
        "-movflags", "+faststart",
    ]
    if args.audio or not args.no_silent_track:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-shortest"]
    cmd += [out]

    print("  " + " ".join(cmd) + "\n")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed with exit code {r.returncode}")

    mb = os.path.getsize(out) / 1024 / 1024
    print(f"\n  wrote {args.out}  {mb:.1f} MB  ({len(pngs)} frames @ {args.fps} fps)")

    probe = shutil.which("ffprobe")
    if probe:
        subprocess.run([probe, "-v", "error", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate,pix_fmt",
                        "-of", "default=noprint_wrappers=1", out])


if __name__ == "__main__":
    main()
