Grapnel Ninja — owner preview and phone checklist

Local preparation only. All owner checks below are NOT PERFORMED. Console access,
phones and moderation do not gate completion of this preparation checklist.

Package identity (paths relative to /opt/grapnelninja):
- Final candidate for these owner checks: artifacts/y8-release/grapnelninja-y8.zip
  (identity, SHA256, build tag and source revision: artifacts/y8-release/manifest.json;
  the kit copy OWNER-CHECKLIST.txt carries the concrete values)
- Build tag in the runtime: `build_tag` in artifacts/y8-release/manifest.json
  (the kit's TEST-RESULTS.txt and OWNER-CHECKLIST.txt repeat it)
- Evidence directory of the current kit: artifacts/<task>/ where <task> is the
  `task` value of artifacts/y8-release/manifest.json (TASK-285 was the first
  such rebuild; later rebuilds replace the kit and the pointer together)
- Inventory and build checks: artifacts/<task>/build/candidate.json, package-check.log
- Exact-ZIP offline checks: artifacts/<task>/functional/release-checks.json
- Media review: artifacts/<task>/media/media-review.json; all nine assets were
  recaptured from this exact ZIP and compared with the TASK-263 captures.
- Native 60-FPS rows: OWNER-CHECKLIST.txt of the runner package recorded in
  artifacts/<task>/readiness.json runner_runtime_binding.runner_package (the
  kit's OWNER-CHECKLIST.txt prints that path; return results/*.json); TASK-284
  reports every row UNVERIFIED until then.
- Verify the selected ZIP with sha256sum before upload and record the hash below.
  A displayed build label alone does not distinguish archives.
- Local preparation only: the measured software-renderer regression against the
  original ZIP (TASK-282) is outstanding; no upload, live ads or submission was performed.

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
