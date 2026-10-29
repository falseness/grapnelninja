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

### Telling freezes apart (`schemaVersion` 2)

A freeze where the game's timed layers add up to a few ms has its cause
outside the game's draw code. These fields help find it. All of them exist
only while recording, and `stop()` (or Export) tears them down:

- `loafs` (with `loafSupported`): Chrome's Long Animation Frames, up to 2000,
  as `{startTime, duration, blockingDuration, renderStart,
  styleAndLayoutStart, scripts}`. `scripts` holds the 3 longest scripts of the
  frame, `{sourceURL, sourceFunctionName, invoker, duration}`. Each freeze's
  `context.loafs` lists the entries that overlap it. `loafSupported` is false
  outside Chromium, and then `loafs` stays empty.
- `freezes[].mainThreadSilenceMs`: while recording, a `MessageChannel`
  heartbeat runs on the main thread, at most one beat per 4 ms. This field is
  the longest time inside the freeze with no beat.
  - Close to `gapMs`: the main thread was blocked (script, style, layout or a
    synchronous canvas operation). `context.loafs` usually names the script.
  - Much smaller than `gapMs`: the main thread was free and the frame came
    late anyway. That points to the GPU, compositor, vsync or the OS.
- `samples[].heapMB`: JS heap in use (`performance.memory.usedJSHeapSize`,
  0.1 MB steps). It exists only in Chromium browsers. A freeze has
  `heapBeforeMB` (the previous sample), `heapAfterMB` and
  `heapDropMB = max(0, before - after)`. A large drop during a freeze with a
  long `mainThreadSilenceMs` points to garbage collection.
- `samples[].rafLagMs` (also on each freeze): how late the frame callback
  started after its `requestAnimationFrame` timestamp.

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
   in the frame that drew it. A CPU-backed image that size also uploads about
   14 MB to the GPU on its first draw. The palette paint is constant along x
   and the dither noise is a 256 px tile, so each palette is now a 256 px wide
   strip drawn side by side from the frame origin (`drawGrappleOverPalette`,
   render/draw.js). `buildGrappleOverPaletteStrips` builds all 8 strips
   (about 11 MB at 1706x932 DPR 1.5) when the frame size is first known and
   again after a resize or DPR change. It draws each strip once into a 1x1
   canvas right away, so a band change builds and uploads nothing.
   The parallax tiles (render/parallax.js, about 3.8 Mpx per band at that
   size) work the same way: `buildGrappleOverParallaxTiles` builds and warms
   the tiles for all 8 bands together and keeps them out of the glow sprite
   LRU. That is about 120 MB, which a full climb already held before.

### First draws (GPU uploads)

A canvas painted on the CPU is probably uploaded to the GPU the first time it
is drawn, so a large image first drawn mid-play can freeze a frame even when
no canvas is created. Palette strips and parallax tiles are therefore built
and drawn once into a 1x1 canvas ("warmed") right after they are built, at
boot and after a resize. Crystal/rock layer tiles depend only on the
viewport size, so they are built at boot and again only on a resize.

`?visualsPerf=1` detects first draws while recording. It wraps `drawImage`
and counts each source the first time it is drawn on the page. In the
exported `visuals-performance.json`:

- `samples[].fd` is the px (source width x height) first drawn in that
  frame. It is left out when 0.
- `freezes[].context.firstDraws` lists the 3 largest first draws of the
  freeze frame as `{src, w, h}`. `src` is the `file:line` that created the
  canvas, or an image url or type. Glow sprites and parallax tiles show as
  `render/glowsprites.js:241`, and palette strips and layer tiles as
  `render/effects.js:<line>`.
  A freeze whose `firstDraws` holds a multi-Mpx canvas that is not a resize
  points to an image that still needs building and warming ahead of time.
  An empty list means the freeze was not a first draw.
- `freezes[].context.palette` is the Grapple Over palette blend of the last
  drawn frame, `{from, to, t}` (band indices and blend weight), or null
  outside Grapple Over. A `t` between 0 and 1 means the freeze happened
  inside a band blend zone.

### Checking

To check after changing render code, re-run
`python3 tools/canvas_audit.py --mode single|double [--resize] [--allowlist <file>] --out <file>`.
It holds the ninja at the 12 recorded freeze points (tools/fixtures/freeze-walk.json) for 2
passes plus a vertical sweep in headless Chromium. It counts the canvases
created and the px first drawn. Expected: pass 2 total (`perPass[1]`) <= 3,
`maxPerFrame` <= 4, `glowMisses.text` 0, `smoothCheck.afterBoot` 0,
`smoothCheck.firstDrawsOk` true, `firstDraw.maxPxPerFrame` <= 500000 and
`firstDraw.framesOver1MpxNotAllowlisted` 0. `firstDraw.large` lists every
single first draw of 1 Mpx or more after boot. `--resize` adds a last
phase (1280x720 and back) whose rebuilds appear only in `large` and `resize`.
The allowlist is a JSON list of `{creator, px, reason, phases}` for the
first draws that are only expected on a resize. The audit counts canvases
and px only; headless frame times say nothing about real freezes.
