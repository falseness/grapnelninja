# Measuring frame rate in your own Firefox

This page is for measuring Grapnel Ninja in **your** Firefox on **your**
machine. The in-game "fps counter" checkbox in the menu and the steps below
measure the player's real browser. Server headless FPS (about 6-7 FPS in the
automated runs) does not reflect a real browser and is not used here.

Nothing on this page talks to Playgama or any other service. The profiler and
the switches only change what is drawn and what is shown on the canvas.

## 1. Serve the repo locally

From the repo root:

```sh
python3 -m http.server 8000
```

Then open `http://<host>:8000/index.html` in Firefox. `<host>` is `localhost`
if Firefox runs on the same machine; otherwise use that machine's address.
Keep the window the size you normally play at and leave the tab in focus
(background tabs are throttled).

## 2. URLs to try, in order

Open each URL, start a run, play for about 20 seconds, then read the panel
(see section 3) and write the numbers into the table in section 5. Reload
between URLs; don't open them side by side.

Baseline, profiler only:

1. `http://<host>:8000/index.html?perf=1`

One layer switched off (`off=<layer>`; names are the profiler's layer names
from `render/draw.js`):

2. `http://<host>:8000/index.html?perf=1&off=background`
3. `http://<host>:8000/index.html?perf=1&off=lights`
4. `http://<host>:8000/index.html?perf=1&off=behindForegroundParticles`
5. `http://<host>:8000/index.html?perf=1&off=playerTrail`
6. `http://<host>:8000/index.html?perf=1&off=world`
7. `http://<host>:8000/index.html?perf=1&off=particlesAndTrails`
8. `http://<host>:8000/index.html?perf=1&off=bloom`
9. `http://<host>:8000/index.html?perf=1&off=playerGlow`
10. `http://<host>:8000/index.html?perf=1&off=colorGrade`
11. `http://<host>:8000/index.html?perf=1&off=player`
12. `http://<host>:8000/index.html?perf=1&off=tutorialHint`
13. `http://<host>:8000/index.html?perf=1&off=ui`
14. `http://<host>:8000/index.html?perf=1&off=fpsCounter`

Lower canvas resolution (`scale` multiplies the backing-store resolution;
the on-screen size and controls stay the same):

15. `http://<host>:8000/index.html?perf=1&scale=0.5`
16. `http://<host>:8000/index.html?perf=1&scale=0.25`

Notes:

- `bloom` is off by default (`STYLE.features.bloom`), so `off=bloom` should
  match the baseline. `tutorialHint` is only drawn until the hint has faded,
  and `fpsCounter` only while the menu's "fps counter" checkbox is on.
- An unknown layer name or a scale outside 0.25..1 is ignored, with one
  warning in the console (F12 → Console).
- Switching a layer off makes the game look wrong on purpose; it is only
  there to see how much that layer costs.

## 3. Reading the overlay

With the profiler on, a panel sits in the bottom-left corner of the canvas
and refreshes every 0.5 s:

```
FPS 58.31  frames 2410
world 3.12 / 5.40
lights 2.05 / 3.80
...
```

- **FPS** is the requestAnimationFrame rate over the last 120 frames, i.e.
  what you actually see. `frames` is the total number of frames drawn.
- Each next line is one draw layer (or `update`, the physics step), the six
  slowest first: **mean ms / p95 ms** over the last 120 frames. Mean is the
  typical cost; p95 is the cost of the slow frames (95% of frames are
  faster). At 60 FPS a whole frame has about 16.7 ms.

From the console, `PERF_PROFILE.snapshot()` returns the same numbers for
every layer.

## 4. What to copy from about:support

Open `about:support` in the same Firefox and copy these lines from the
**Graphics** section:

- **Compositing** (e.g. `WebRender`, `WebRender (Software)`)
- **GPU #1** (and GPU #2 if present): Description, Vendor ID, Device ID,
  Driver Version
- Under **Features**: **WebRender**/**Compositing** status, **Direct2D**
  (Windows only)
- Under **Diagnostics**: **AzureCanvasBackend** (canvas backend, e.g.
  `skia` or `direct2d 1.1`) and **AzureCanvasAccelerated**

Also note the Firefox version, the OS, the window size and the display
scale (e.g. 100% / 200%).

## 5. Results table

Fill in one row per URL (FPS from the panel's first line; top 3 layers as
`name mean/p95`):

| URL | FPS | top 3 layers |
| --- | --- | --- |
| perf=1 | | |
| off=background | | |
| off=lights | | |
| off=behindForegroundParticles | | |
| off=playerTrail | | |
| off=world | | |
| off=particlesAndTrails | | |
| off=bloom | | |
| off=playerGlow | | |
| off=colorGrade | | |
| off=player | | |
| off=tutorialHint | | |
| off=ui | | |
| off=fpsCounter | | |
| scale=0.5 | | |
| scale=0.25 | | |

about:support:

```
Firefox version:
OS:
Window size / display scale:
Compositing:
GPU #1:
AzureCanvasBackend:
AzureCanvasAccelerated:
Direct2D:
```

## 6. What happens next

Optimization tickets will be cut after you report these numbers. Which
layers they target, and whether lowering the resolution is worth it,
depends on what your Firefox shows.
