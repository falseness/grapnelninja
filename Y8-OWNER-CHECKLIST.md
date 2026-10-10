Grapnel Ninja — owner preview and phone checklist

Local preparation only. All owner checks below are NOT PERFORMED. Console access,
phones and moderation do not gate completion of this preparation checklist.

Package identity (paths relative to /opt/grapnelninja):
- Final candidate for these owner checks: artifacts/TASK-267/grapnelninja-y8.zip
- SHA256: c96a029eaff51071ea0bab0d260981dd14c0c91629097d49784e812eda01bc12
- Build: 2026-10-10-y8-candidate267; size: 101612 bytes
- Source: d858abc8a755d071ee79b76d35e3667bee10e981
- Inventory: artifacts/TASK-267/candidate.json
- Exact-candidate offline checks: artifacts/TASK-268/release-checks.json
- Current copy/media instructions: Y8-MEDIA-HANDOFF.md
- Media review: artifacts/TASK-269/media-review.json; all nine TASK-263 assets
  are reused historical captures, NOT newly captured final-build screenshots.
- artifacts/y8-release/ contains an older archive and historical instructions.
  Do not select that archive or its stale recapture claim for this handoff.
- Verify the selected ZIP with sha256sum before upload and record the hash below.
  A displayed build label alone does not distinguish archives.
- Local preparation only: inherited matched-density performance failures still
  block package readiness; no upload, live ads or submission was performed.

Record for EACH run:
Date/time: ____  Phone model: ____  OS/version: ____  Browser/version: ____
ZIP path/SHA256/source: ____  Displayed build: ____  Preview URL: ____
Orientation/fullscreen: ____  Viewport/DPR/render density: ____
DevTools closed/docked/undocked: ____  CPU throttle: ____  Emulation: ____
Mode/seed/actions/duration: ____  Result (PASS/FAIL/NOT PERFORMED): ____

[ ] Owner uploads the selected ZIP to the existing game's private preview;
    index.html is at archive root. First launch reaches a responsive menu with
    no loading or consent overlay trapping input. Capture the first launch.
[ ] Android Chrome and iPhone Safari: start BOTH Main and Chill; tap, hold and
    release grapple. Movement responds; release and touch cancellation do not
    leave a stuck hook. Specifically reproduce the reported mobile rejection.
[ ] Open portrait, rotate both directions, and test Y8 fullscreen on/off.
    Game remains visible, menus fit and taps hit the displayed controls.
[ ] Interrupt a held touch with a system gesture or backgrounding; return and
    resume. No stuck hook, unintended movement or simulation catch-up jump.
[ ] Pause/resume, play to a natural lethal death, restart and return to menu; controls remain usable.
    Reload: records/language persist when storage is permitted.
[ ] Optional rewarded Continue: verified viewed/reward callback rewards once;
    dismissed/no-fill/blocked/error does not reward. After terminal outcome,
    Restart/menu/input remain usable; repeated clicks do not duplicate requests.
    Record actual hosted SDK behavior and ad outcome; mocks do not certify ads.
[ ] Investigate the reported approximately 60-to-10 FPS drop: same device,
    browser, viewport, DPR, render density, mode, seed/actions and duration for
    old and candidate builds. Use 3 x 30-second active-play runs. Record average,
    each 10-second window and frame-time spikes; exclude menu/background time.
    Start with DevTools closed and CPU throttling disabled, then repeat docked
    and undocked, recording emulation on/off and throttle for every run.
    For a matched baseline near 60 FPS, expected average >=55 FPS and no
    unexplained 10-second window below 30 FPS; record failures, not just peaks.
    Reduced-resolution FPS gains are not equal-quality optimization gains.
    Record any density change/softening separately. Local headless measurements
    do not establish physical-device performance or resolve the reported drop.
[ ] Owner records smoothness on actual phones and retains any failing replay.
    Owner checks current console media fields/limits, title, controls, mobile
    support and orientation before deciding whether to submit for moderation.

Failure evidence: screen recording from first launch through the exact failing
steps; expected versus observed behavior; timestamp, mode and seed/actions;
phone/OS/browser, ZIP SHA256, preview URL, orientation/fullscreen, viewport/DPR,
render density, DevTools/throttle/emulation settings, FPS samples and console
errors. Preserve a screenshot and network/console log if available.

Archived completed local checks: artifacts/TASK-268/release-checks.json and its
manifest bind release, embed, mobile, lifecycle and ad fixtures to this exact ZIP.
Gameplay is silent; SDK sound starts off. Confirm ad recovery without inventing
an audio-resume check or interstitial support (the Y8 adapter disables it).
Physical Android/iOS, interactive DevTools reproduction, hosted ads, console
upload and moderation remain NOT PERFORMED. No moderation success is claimed.
