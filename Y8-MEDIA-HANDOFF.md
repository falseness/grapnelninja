# Y8 candidate media and copy

Use this handoff and Y8-OWNER-CHECKLIST.md for the TASK-268 verified candidate:
`artifacts/TASK-267/grapnelninja-y8.zip`, build `2026-10-10-y8-candidate267`,
SHA256 `c96a029eaff51071ea0bab0d260981dd14c0c91629097d49784e812eda01bc12`,
source `d858abc8a755d071ee79b76d35e3667bee10e981` (101612 bytes).
The older `artifacts/y8-release/` bundle and its copy are historical; do not use
its archive or its claim that media was recaptured from this candidate.

## Listing draft

Title: Grapnel Ninja.
Description: Swing through a neon obstacle course with a grappling hook, avoid hazards and chase your record.
Modes: Choose Main for the harder course or Chill for a relaxed run.
Controls: Click or tap and hold to throw the grappling hook; release to let go.
Pause: Use the on-screen menu; desktop P or Escape toggles pause during an active run.
Continue: With the rewarded SDK available, a death at score 5 or above can offer one optional rewarded Continue per run; Restart remains available on the offer except while an ad request is pending.
Ads: Only a completed viewed reward grants Continue; dismissal, no-fill, blocking, errors or timeout do not reward, and this Y8 adapter does not support interstitials.
Audio: Gameplay is silent; the SDK initializes with sound off, and there is no gameplay audio to restore after an ad.
Orientation: On touch-first portrait viewports the landscape stage rotates clockwise; desktop portrait viewports do not use that rotation.
Quality: Adaptive render density may reduce resolution and soften the image under sustained load; FPS gains from lower resolution are not equal-quality optimization gains.

## Reviewer response draft — owner must validate before sending

The candidate retains touch cancellation, focus handling, portrait presentation and visibility-save fixes, with bounded glow drawing that preserves the sampled appearance.
Offline checks against this exact archive passed across local desktop and emulated mobile browser profiles, including interrupted input and rewarded-ad fixtures; these are not native-phone or hosted-ad results.
The six covers and three gameplay screenshots are reused historical TASK-263 captures from source `15aab2256304498eac44d2f37773a7b70174c1da`, not newly captured final-build screenshots.
The inherited matched-density performance regression remains unresolved; native phones, Y8 preview/fullscreen, live ad outcomes, console slots and moderation remain owner checks, and no readiness, guaranteed FPS or resolved rejection is claimed.

## Selected media

Six PNG covers in `artifacts/TASK-263/media/`: `cover-1280x720.png`,
`cover-1920x1080.png`, `cover-512x512.png`, `cover-800x1200.png`,
`cover-800x600.png`, `cover-800x800.png`.
Three PNG screenshots in `artifacts/TASK-263/screenshots/`:
`landscape-bad-seed4-t180.png` (1920×1080),
`main240-bad-seed4-t240.png` and `main300-bad-seed4-t300.png` (2880×1620).

The six covers crop/resize real Main frames and add the title; the three
screenshots preserve the gameplay HUD. The original capture archive SHA256 is
`e2dfd6a06953a80ea863c062bf3616f11e01bee4b8c67a9101f88f59eabb1681`.
Between capture and candidate, packed changes affect glow destination bounds
and the build tag, with no changed controls, HUD, palette or gameplay content.
Review found no asset made inaccurate by those changes; reuse represents the
appearance, not proof of universal pixel equality or current-device sharpness.

`artifacts/TASK-269/media-review.json` records original capture dates/revisions,
actual dimensions, formats, byte sizes, hashes and individual visual findings;
`contact-sheet.png` shows all nine selected assets. `handoff-review.json` maps
the copy above to candidate source and archived verification. `manifest.json`
seals this review's commands, environment and evidence hashes.
Exact console slot dimensions, formats, byte/count limits and any video
requirement remain owner-verified; these local choices do not establish them.
