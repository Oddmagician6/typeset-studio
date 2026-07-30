# Promo reels

Two advertising cuts for Typeset Studio, both built from **real footage of the
running app** — no mockups. The book shown throughout is a genuine 59-page
composition (5 chapters, Fantasy Epic 6×9, Fantasy Emerald cover) whose preflight
comes back *All clear*.

| File | Aspect | Length | For |
|---|---|---|---|
| `typeset-studio-reel.html` | 16:9 | 60s | landing page, YouTube |
| `typeset-studio-reel-9x16.html` | 9:16 | 27s | Instagram / Facebook Reels, TikTok |

Both are single self-contained HTML files with every image inlined as a data URI,
so they work offline and can be published as-is. Open either in a browser to
watch; the 9:16 one has a **Safe area** button that outlines the region
Instagram's own caption, audio strip and action buttons sit outside of.

## Rendering an MP4

Only needed for the vertical cut (Reels will not take an HTML page). Two
one-time installs:

```
winget install --id Gyan.FFmpeg -e
py -m venv .venv-video
.\.venv-video\Scripts\python.exe -m pip install playwright pillow
.\.venv-video\Scripts\python.exe -m playwright install chromium
```

Open a **new terminal** afterwards so `ffmpeg` is on `PATH`. Then:

```
.\.venv-video\Scripts\python.exe promo\render_frames.py      # 810 PNGs, ~2 min
python promo\encode.py                                       # -> mp4
```

Spot-check a single beat without rendering all 810 frames:

```
.\.venv-video\Scripts\python.exe promo\render_frames.py --start 16 --end 18
```

The 16:9 cut can be rendered too:

```
.\.venv-video\Scripts\python.exe promo\render_frames.py --src typeset-studio-reel.html --w 1920 --h 1080
python promo\encode.py --fps 30 --out typeset-studio-reel-16x9.mp4
```

### Why Playwright rather than a screen recording

Each reel exposes `window.__reel.seek(t)`, and every animation on the page is a
**paused Web Animation whose `currentTime` is written from that `t`**. Nothing
runs on its own clock. So the renderer advances the playhead one frame at a time
and takes a still: no dropped or duplicated frames, and the same `t` always
produces the same pixels. A real-time capture cannot promise that.

## Audio

Both cuts render **silent on purpose**, with the message carried by on-screen
type. Add a trending track in the Instagram editor — in-app audio reaches further
than baked-in music, and it avoids a licensing question.

To bake a track in instead:

```
python promo\encode.py --audio my-track.mp3
```

Encoding targets what Meta wants: H.264 High profile, `yuv420p`, 30 fps,
`+faststart`, plus a silent AAC track (some upload paths reject a video with no
audio stream at all).

## Rebuilding after a change

`*.src.html` are the sources; the shipped files are generated.

```
python promo\pack_assets.py      # 16:9 stills  -> assets.js
python promo\pack_vertical.py    # 9:16 stills  -> assets_v.js
python promo\build.py            # both sources -> both shipped files
```

`build.py` emits **pure ASCII** (numeric entities for visible glyphs) because a
published page's `<head>` — and therefore its charset — is not under our control,
and a mis-decoded em dash shows up as `â€"`.

Regenerating the stills themselves needs the app running at `127.0.0.1:5050`
plus `render_assets.py`; see `pack_*.py` for the crop boxes, which are measured
to the app's content box so the UI reads about twice as large as a raw capture.
