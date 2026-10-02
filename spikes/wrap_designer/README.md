# Wrap designer spike (roadmap #72, phase A)

A throwaway-quality prototype that answered the questions phase A had to answer
before building a freeform wrap designer. It isn't wired into the app.

    python spikes/wrap_designer/server.py        # then open http://127.0.0.1:5099/
    http://127.0.0.1:5099/#selftest               # proof + page-count + drag check
    http://127.0.0.1:5099/measure                 # text measurement harness

| File | What it is |
|---|---|
| `model.py` | The design document (elements anchored to panels, in inches) and `build_pdf`, which renders it with ReportLab using `engine.wrap_geometry`. |
| `wd.js` | Width tables, the line breaker (a port of `engine._wrap_tracked`) and font loading, shared by the editor and the harness. |
| `editor.html` | The SVG editor: guides, select, drag, resize, snap to panel centre, arrow-key nudge, properties, add text/shape, page count, Proof. |
| `measure.html` | Breaks real prose three ways in the browser for the server to compare against the engine. |
| `server.py` | Serves all of it; `/build` makes the real PDF and returns a picture of it plus its line breaks. |

## Findings

**Line breaks: identical, by construction, if the editor measures with ReportLab's own width
tables.** The harness broke 20 paragraphs of real prose (the sample and the local manuscripts)
in all 21 bundled fonts at 3 sizes, 7 box widths and 2 trackings, 17,640 cases:

| How the editor measures | Same lines as the PDF |
|---|---|
| ReportLab's advance-width tables, sent to the browser (`/metrics`) | **17,640 / 17,640** |
| The browser's own `measureText`, kerning and ligatures off | 17,635 / 17,640 |

Five mismatches is the trap: a blurb that breaks differently in the editor than in print is
the one failure a "what you see is what prints" editor can't have, and it would only show up
on the occasional word that lands exactly on the edge. The tables make the browser do the same
arithmetic as ReportLab, so there is nothing left to disagree about.

That arithmetic has to be bit-exact, which turned up one subtlety: ReportLab sums widths with
Python's `sum()`, and since Python 3.12 that uses Neumaier compensated summation for floats.
Most bundled fonts have integer widths (exact either way), but Crimson Pro's em isn't 1000
units, so its widths are floats. `wd.js` mirrors CPython's `cs_add` / `cs_to_double`, switched
on by a `float` flag in the table.

**What's drawn matches too.** With `font-kerning: none` and ligatures off (ReportLab does
neither), the width SVG renders a line at is within **0.001%** of the table width in every font
— so lines don't just break alike, they look the same length.

**The editor itself was cheap.** A hand-rolled SVG editor with guides drawn from
`wrap_geometry`, selection, drag, corner resize, centre snapping, nudging, a properties panel
and a Proof round trip is ~380 lines, no dependencies. SVG's user units are set to inches, so
the editor's coordinates are the design document's coordinates, with no conversion layer. The
self-test checks: every text box's lines match the PDF; raising the page count from 320 to 640
widens the spine 0.8" and moves the front title exactly 0.8" while the spine text stays
centred; and a 120 px drag moves the title exactly 120 px worth of inches.

## Decision

**Hand-rolled SVG, not Fabric.js / Konva.js.** The deciding fact is the table above: a canvas
library measures and breaks text with the browser, which is the 5-in-17,640 route, so its
text layer would have to be replaced anyway — and that is most of what a library would have
saved. Without one the offline / no-build convention holds, and the design document stays the
single model rather than a second one kept in step.

## Carried into phase B

- **Missing glyphs.** A character a font lacks is drawn by a browser fallback font but as a
  blank in ReportLab. The editor should flag any character absent from the width table.
- **No kerning in print.** ReportLab doesn't kern, so display type ("To", "AV") sets a little
  loose. True of today's template covers too; manual tracking is the remedy for now.
- **Not yet covered:** image crop/zoom (cover-fit only), the image dpi check, rotation other
  than 0°/90°, justified blurbs, undo, layers panel, "Customise this design" from a template,
  and a re-render that doesn't redraw everything on every pointer move.
- **Check in WebKit.** Measured in Chromium (what the Windows app runs in, via WebView2). SVG
  `letter-spacing` and the font-feature switches should be confirmed in Safari/WKWebView before
  a macOS build.
