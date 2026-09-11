"""Render the reel to a numbered PNG sequence with headless Chromium.

    python render_frames.py                      # 9:16, 30 fps
    python render_frames.py --fps 24
    python render_frames.py --src typeset-studio-reel.html --w 1920 --h 1080

Why Playwright and not a screen recording: the page exposes window.__reel.seek(t),
and every animation on it is a paused Web Animation whose currentTime is written
from that t. So we advance the playhead ourselves, one frame at a time, and shoot
a still. Nothing races a real-time clock, no frame is dropped or duplicated, and
the same t always produces the same pixels.

Run encode.py afterwards to turn the sequence into an MP4.
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# The frame cache defaults OUTSIDE the repo: a 27s reel is ~800 PNGs / 300 MB,
# which no working copy wants - least of all one inside a synced cloud folder.
FRAMES = os.path.join(tempfile.gettempdir(), "typeset-reel-frames")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="typeset-studio-reel-9x16.html")
    ap.add_argument("--out", default=FRAMES)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    ap.add_argument("--start", type=float, default=0.0, help="seconds, for spot checks")
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--keep", action="store_true", help="do not wipe the frames dir first")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "Playwright is not installed in this interpreter.\n"
            "  py -m venv .venv-video\n"
            "  .\\.venv-video\\Scripts\\python.exe -m pip install playwright pillow\n"
            "  .\\.venv-video\\Scripts\\python.exe -m playwright install chromium\n"
            "then run this script with .venv-video\\Scripts\\python.exe"
        )

    src = os.path.join(HERE, args.src)
    if not os.path.exists(src):
        sys.exit(f"no such reel: {src}")

    outdir = os.path.join(HERE, args.out)
    if os.path.isdir(outdir) and not args.keep:
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)

    url = "file:///" + src.replace("\\", "/") + f"?render=1&fps={args.fps}"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            # keep rasterisation deterministic frame to frame
            "--force-color-profile=srgb",
            "--disable-lcd-text",
            "--hide-scrollbars",
        ])
        page = browser.new_page(viewport={"width": args.w, "height": args.h},
                                device_scale_factor=1)
        page.goto(url, wait_until="load")
        page.wait_for_function("window.__reel && window.__reel.ready", timeout=60_000)
        if page.evaluate("window.__reel.ready") == "timeout":
            print("  ! fonts/images did not settle within 15s - frames may show "
                  "fallback type; check the first frame before encoding")

        total = page.evaluate("window.__reel.total")
        stage = page.locator("#stage")
        box = stage.bounding_box()
        if round(box["width"]) != args.w or round(box["height"]) != args.h:
            print(f"  ! stage is {box['width']}x{box['height']}, expected "
                  f"{args.w}x{args.h} - check the body.render CSS")

        t0, t1 = args.start, (args.end if args.end is not None else total)
        first = int(round(t0 * args.fps))
        last = int(round(t1 * args.fps))
        n = last - first
        print(f"  {args.src}  {total:.2f}s  {args.fps} fps  ->  {n} frames "
              f"at {args.w}x{args.h}")

        began = time.time()
        for k in range(first, last):
            page.evaluate("n => window.__reel.seekFrame(n)", k)
            stage.screenshot(path=os.path.join(outdir, f"f_{k:05d}.png"),
                             animations="disabled")
            if (k - first) % 60 == 0 and k > first:
                done = k - first
                rate = done / (time.time() - began)
                print(f"    {done}/{n}  {rate:.1f} fps  "
                      f"eta {(n - done) / max(rate, .01):.0f}s")

        browser.close()

    took = time.time() - began
    size = sum(os.path.getsize(os.path.join(outdir, f))
               for f in os.listdir(outdir)) / 1024 / 1024
    print(f"\n  {n} frames in {took:.0f}s  ({size:.0f} MB) -> {outdir}")
    print(f"  next: python encode.py --fps {args.fps}")


if __name__ == "__main__":
    main()
