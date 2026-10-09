# Playgama artwork refresh

TASK-247 delivers ten real Main-mode browser screenshots and three generated
promotional covers. Local deliverables live in `artifacts/TASK-247/` and are
intentionally excluded from Git, along with `screenshots/`.

- `screenshots/main-01.png` through `main-10.png`: native 1280×720 browser captures.
- `screenshots/capture.json`: revision, source hashes, seeds, trusted input events,
  viewport, browser version and gameplay state; `contact-sheet.jpg` is an overview.
- `covers/grapnel-ninja-800x800.png`, `grapnel-ninja-1080x1920.png` and
  `grapnel-ninja-1920x1080.png`: screenshot-referenced generated covers, each <10 MB.
- `artwork.json`: full prompts, reference/generated/final hashes and metadata.
- `review.md`, `manifest.json`, `verifier.log`: individual native visual review,
  reproducibility information and independent evidence inspection.

Capture again into a new directory with:

```sh
python3 tools/capture_playgama_artwork.py --out artifacts/TASK-247-rerun
```

This serves the current application locally, clicks Main through trusted browser
input and captures unmodified real-time rendering. Only seeded randomness and the
SDK network boundary are controlled. Early-run frames legitimately show score zero.
Timestamped inputs support replay investigation; real-time scheduling means pixel
identity across machines is not guaranteed. This is not a live-portal certification.

The three covers used the built-in image generation tool with the first current
capture as the reference, followed by ImageMagick sizing. They are promotional
artwork, not real screenshots. Original generated sources and exact prompts are
retained in the evidence directory. Existing itch artwork is preserved. No later
ticket, upload or release operation is required for this deliverable.
