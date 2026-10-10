Grapnel Ninja — owner preview and phone checklist

Local preparation only. All owner checks below are NOT PERFORMED. Console access,
phones and moderation do not gate completion of this preparation checklist.

Package identity (paths relative to /opt/grapnelninja):
- Current accepted gameplay ZIP: artifacts/TASK-261/grapnelninja-y8.zip
- SHA256: e2dfd6a06953a80ea863c062bf3616f11e01bee4b8c67a9101f88f59eabb1681
- Size: 100061 bytes; source: 15aab2256304498eac44d2f37773a7b70174c1da
- Inventory: artifacts/TASK-261/candidate-release.json
- Final-package location: artifacts/y8-release/grapnelninja-y8.zip
  That location currently contains the OLD 99788-byte ZIP, SHA256
  baf5e3bee031d6c238c3afa074109e22030bb1cff89e6740409643a88d613394.
  Do not mistake it for the current accepted ZIP above. Package assembly is a
  separate task; this checklist is usable with the accepted ZIP immediately.
- Release manifest: artifacts/y8-release/manifest.json
- Owner upload instructions: artifacts/y8-release/UPLOAD.txt (its build/media
  references describe the old bundle). Current media: artifacts/TASK-263/media/
  and artifacts/TASK-263/screenshots/; inventory: artifacts/TASK-263/media-manifest.json.
- Verify the selected ZIP with sha256sum before upload. Record its SHA256 below;
  a displayed build label alone does not distinguish these archives.

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
[ ] Pause/resume, lose, restart and return to menu; controls remain usable.
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

Archived completed local checks: artifacts/TASK-262/release-smoke.json and its
manifest describe 18 local emulated browser cases with mocked SDK availability.
Physical Android/iOS, interactive DevTools reproduction, hosted ads, console
upload and moderation remain NOT PERFORMED. No moderation success is claimed.
