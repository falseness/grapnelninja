# grapnelninja
Html 5 konva simple game

Mobile play supports landscape orientation. Portrait shows a rotate prompt and pauses an active run; rotate back and tap Resume to continue.

## Grapple Over: grapnel range

Single grapnel is the intended way to play. Double grapnel mode (pause menu toggle "Grapnel: single / double range") doubles the grapple range as an easier option, both before and after the range upgrade. Switching keeps the run going (position, time and best height); a run that used double range stays marked as such.

## Recording freezes in your own browser (`?visualsPerf=1`)

The server's headless browser has no GPU, so its frame times do not show the
freezes players see. To record them on your own device:

1. Open the game with `?visualsPerf=1` added to the address, e.g.
   `http://<host>:8000/index.html?visualsPerf=1`. A small panel appears in the
   bottom-left corner.
2. Press **Start**, then play until a freeze happens. The panel counts freezes
   (frames over 50 ms), shows the worst one and the slowest layer of the last one.
3. Press **Export**. This stops the recording and downloads
   `visuals-performance.json`. Send that file for analysis.

Without the flag nothing is recorded and no panel is shown. Nothing is sent
anywhere; the file stays on your device until you send it. `?visualsPerf=1`
can be combined with `?perf=1`.

## Perf note: freezes from runtime canvas creation

A Chrome recording (v20, 1706x932, DPR 1.5) showed 67-117 ms freezes with only
3-6 ms of measured work and 1-3 canvases created in every freeze frame. Three
caches created canvases during play:

1. **HUD text.** `drawGlowText` (render/glowsprites.js) built one glow sprite
   per whole string, so every new `Time: 4.0 s` / `Height: 2935` value made a
   canvas and thrashed the 96-sprite LRU. Changing HUD strings now go through
   `drawGlowGlyphs`: one sprite per character, subpixel phase and row style.
   The sprites are cells of shared 1024 px atlas pages (`buildGlyphCell`), so a
   new glyph creates no canvas.
2. **Bounce board contacts.** `cacheBounceContact` (render/roledetail.js) made
   one canvas per trace segment, up to 63 in a frame when a board first
   appeared. Each board's segments and vias are now packed into one atlas
   canvas, and the contact dot and scratch canvas are shared
   (`BOUNCE_MATERIAL`).
3. **Grapple Over palette images.** `BackgroundRenderer.getSmoothImage`
   (render/effects.js) rebuilt a full-frame (2559x1398) dithered palette image
   in the frame that drew it, because `drawGrappleOverPalette`
   (render/draw.js) kept only 3. It keeps 4 now, and `drawBackgroundLayer`
   builds the next neighbour palette ahead (`grappleOverPaletteAhead`,
   `prebuildGrappleOverPalette`). That is at most one build per frame, never
   in a frame that built a drawn image, and about 25 frames before its first
   draw.

To check after changing render code, re-run
`python3 tools/canvas_audit.py --mode single|double --out <file>`. It holds the
ninja at the 12 recorded freeze points (tools/fixtures/freeze-walk.json) for 2
passes plus a vertical sweep in headless Chromium and counts the canvases
created. Expected: pass 2 total (`perPass[1]`) <= 3, `maxPerFrame` <= 4,
`glowMisses.text` 0, and `smoothCheck.leadOk` true. The audit counts canvases
only; headless frame times say nothing about real freezes.
