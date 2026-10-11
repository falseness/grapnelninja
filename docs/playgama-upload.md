# Playgama repair archive — 2026-10-11

TASK-297 uploaded the exact verified TASK-296 repair ZIP to the existing Grapnel
Ninja application `cmuu1nvs30d00hj0h49c07spq`. Playgama confirmed the upload and
reported processing `DONE`, certification `PASSED`, and Bridge `FOUND` (2.3.1).

- Archive: `cmv4c2pch08dtnk0h2r6nkj7e` (`grapnelninja-2026-10-11-start-firefox`).
- Source revision: `d36f68e53ff4cf2c2b003c52cdd8c6b7a6b4ab65`.
- ZIP: `artifacts/TASK-296/release/grapnelninja-2026-10-11-start-firefox.zip`.
- Size: 91541 bytes; SHA-256: `bbbdfcc236f1c2377e16e962e7c4366616dfb2ec484e1f81ad956e7679f73836`.
- Official QA: https://developer.playgama.com/qa-tool/cmv4c2pch08dtnk0h2r6nkj7e

The sandbox still uses archive `cmv0yeu170489oj0iy0psx1i2`. This task did not
publish the sandbox, submit moderation, start traffic, or spend money. The
existing application moderation rejection remains; archive certification does
not constitute moderation approval. Native Android Firefox remains unverified,
repair-build performance was not measured, and no performance improvement is
claimed. Native iOS/Safari and successful served-ad creative behavior also remain
unverified.

The current 36-item checklist, exact-byte preflight, sanitized upload receipt,
server status history, hosted QA results, and hashed evidence manifest are in
`artifacts/TASK-297/`. These files are intentionally untracked. Retain this archive
ID for any follow-up; do not allocate another archive to repeat this upload.

Hosted Chromium checks passed in both modes with desktop and emulated touch
input: real SDK readiness, movement, progress/settings save and reload, and no
page exceptions or configuration error. The first process exited with code 143
after the two desktop passes; its partial evidence is preserved, and both touch
cases passed a separate run with unchanged assertions.

## Historical release — 2026-10-09

The corrected game is uploaded and live in the existing public sandbox:
https://playgama.ai/play/kjkngkpxox

- Application: `cmuu1nvs30d00hj0h49c07spq` (Grapnel Ninja).
- Runtime revision: `83e53def34212794aba437c0d0b5e807a315afbe`.
- Archive: `cmv0qzlea00bxqm0hnjsvkx55` (`grapnelninja-playgama-83e53de`).
- ZIP: `artifacts/playgama-ready-20261009/release/grapnelninja-playgama.zip`.
- Size: 104365 bytes; SHA-256: `1abba97b75ef5c8da59aae434e6a5389876351626c5024cd6d8fd9be21e05c3f`.
- Processing: DONE / PASSED / Bridge FOUND (2.3.1).
- Sandbox revision: `cmv0r7uno00hfoj0idyijg4a1`, read back against that archive.
- QA: https://developer.playgama.com/qa-tool/cmv0qzlea00bxqm0hnjsvkx55

This supersedes the `2fd723f` ZIP and its configuration-path error. Do not upload
that older ZIP again. Older receipts and unsuccessful diagnostic attempts remain
in their original artifact directories.

## Corrections

Bridge initialization passes `./playgama-bridge-config.json`, rather than an
absolute URL. Hosted QA no longer displays the configuration-path error.
A regression check rejects absolute configuration URLs and exercises nested paths.

Progress and settings persist only through Bridge Storage. The former direct
browser-storage cache/journal was removed to comply with the current required
Storage integration. Pending changes stay in memory during an SDK outage and
merge safely on recovery. SDK writes are batched. Confirmed saves survive reload;
closing the page before an unavailable SDK has saved cannot persist those unsaved
changes. Cloud progress is not overwritten by startup defaults.

The saved English/Russian description and controls now describe free restarts,
not the removed rewarded-continue offer. Other listing fields remain intact.

## Verification

Evidence is under `artifacts/playgama-ready-20261009/`:

- `release/verification.json`: ZIP integrity, reproducibility, 37 exact source
  blobs, exclusions, relative config and absence of direct browser persistence.
- `release-smoke/smoke.json`: eight extracted-only desktop/touch, Main/Chill,
  normal/rejected-SDK cases; real input and measured audible/muted/restored audio.
- `browsers/`: 25 cold/fault/throttled cases across Chromium, Firefox and WebKit.
- `storage/`: delayed/rejected reads and writes, safe reconciliation, SDK reload,
  bounded waits, and zero direct browser-storage accesses.
- `history/history.json` Main case and `history-chill/history.json`: two-minute
  real-input gameplay per mode, natural deaths/restarts, three history cycles,
  exact saved progress/settings preservation. The earlier Chill input probe used
  150ms presses that often never attached; the rerun holds for one second while
  retaining all movement/progress assertions. The unsuccessful run is preserved.
- `hosted-chromium/hosted.json` desktop cases and `hosted-touch/hosted.json`:
  real hosted SDK, both modes, readiness, input, movement, mute/language/tutorial
  persistence through reload, no game exceptions or config-path error. Earlier
  harness failures (canvas selection, menu-only language control, cached HTTP 304,
  and tap versus hold) are preserved separately or labeled in the case results.
- `sandbox-smoke/` and `sandbox-phone/`: actual public sandbox, desktop Main and
  Pixel 7 landscape-emulated Chill, real SDK saves/reloads and native captures.
- `host-controls/verification.json`: real host pause/audio events; restoration
  when the iframe regains focus. Player-controlled resume remains intentional.
- `host-ad/ad.json`: natural death, real interstitial loading/failed outcome,
  free Restart and restored audio. No successful served creative is claimed.

## Remaining publication checks

The game has NOT been resubmitted for moderation. `get_submission_state` allows
submission and reports existing EXTENDED certification; this is not a new
physical-device test or a moderation receipt.

The Linux hosted WebKit check remains unverified: the QA page crashes on both
old and fixed archives without GStreamer autoaudiosink; an isolated dependency
avoids the initial crash but the interactive check stalls. The headed alternative
cannot start without GTK4. Local WebKit checks pass. Preserve the control logs;
do not label this as a proved game regression or native Safari success. Native
Safari/iOS/Android and legacy operating systems have not been tested here.

The three covers are already uploaded. Listing screenshots still require the
authenticated developer console, which is separate from MCP OAuth. Replace them
with main-01, main-02, main-04 and main-10 from:
`artifacts/TASK-249/upload-20261009T085213Z/selected-screenshots.zip`.
Save and read back their media IDs and capture the saved listing. Do not upload
the game ZIP or covers again for this cosmetic step. Final moderation submission
also requires the console; no supported MCP submit operation is exposed.

Never commit `artifacts/` or `screenshots/`; existing itch deliverables are unchanged.
