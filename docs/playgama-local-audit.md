# Playgama local requirements audit

Reviewed 2026-10-09 for TASK-246 against the official [technical](https://wiki.playgama.com/playgama/game-requirements/technical-requirements), [advertising](https://wiki.playgama.com/playgama/game-requirements/advertising-requirements), [UX](https://wiki.playgama.com/playgama/game-requirements/user-experience-requirements), and [self-check](https://wiki.playgama.com/playgama/game-requirements/game-self-check) documentation.

The clause matrix, dated reference snapshots, source hashes, rerun logs and inspection results live in `artifacts/TASK-246/`. They are deliberately untracked. Run `python3 tools/verify_playgama_audit.py artifacts/TASK-246` to inspect their integrity and coverage. A passing audit means the local review is complete, including identified failures and unavailable checks; it does not certify release compliance.

## Local declarations

- Languages: English (`en`) and Russian (`ru`), with platform-language initialization, saved selection, and a globe/native-name toggle.
- Devices: desktop keyboard/mouse; mobile touch in landscape. Portrait displays a rotate prompt and pauses gameplay. These are intended capabilities, not a claim about an uploaded listing.
- Setting: an endless grappling arcade game with Classic and Chill modes, saved records, synthesized audio, mute, and first-run guidance.
- Advertising: Bridge interstitials at game over, with a 120-second cooldown. Continue is free. No rewarded-ad offer, payments, banners, external login, or external analytics is implemented.

## Release gaps

1. **Increasing difficulty (UX 4): FAIL.** Current obstacle weights, spacing rules and physics constants do not establish a score/time-based difficulty progression. Random variation and two selectable modes do not prove increasing difficulty. A designed and playtested progression is needed; changing game balance is outside this focused audit.
2. **Browser/OS compatibility: unverified beyond the recorded Linux engines.** Chromium, Firefox and Playwright WebKit runs do not certify Google Chrome, Edge, Opera or native Safari, Windows Vista/7/8/10, macOS 10.6+, Android 5+, or iOS 9+. Obtain actual supported environments, exercise controls/storage/ads/audio/resize, and record versions and results. Legacy JavaScript/WebAudio compatibility must be measured.
3. **Physical mobile behavior: unverified.** Touch emulation proves local layout and input paths only. Fullscreen permissions, OS background audio, native long-press/system-player behavior and orientation need device checks. No explicit browser fullscreen request exists; viewport filling alone does not prove fullscreen compliance.
4. **Runtime coverage: incomplete.** Existing fault, resize, rotation and pause checks cover bounded scenarios. Extended play, navigation history transitions and all native OS interactions are not established. Earlier desktop aspect-ratio captures predate mobile input changes; current source geometry and current browser smoke runs are supporting evidence, not a replacement for the full desktop matrix.
5. **Content provenance and subjective quality: unverified.** Local interaction and procedural rendering do not establish asset rights, catalog originality or sufficient human visual refinement. Review provenance and originality separately.

Packaging, uploaded listing/media, hosted QA and moderation submission are excluded from the local completion gate. Archive size/root naming, listing-language/name/device agreement and live ad placement remain separate release checks. They are recorded as excluded/unverified, never as successful checks or prerequisites to completing TASK-246.

## Evidence reuse

TASK-244 and TASK-245 evidence is reusable because recorded runtime source hashes match this audit's baseline. Their emulation and SDK-fixture limitations still apply. Older readiness, storage, audio, tutorial and advertising evidence predates changes and is replaced by focused reruns. Historical desktop captures are marked historical. All matrix evidence includes an exact SHA-256, and the manifest records commands, environment and exclusions. Re-audit after runtime changes or documentation changes.

The optional legacy `test_i18n.py` suite still assumes a build without Bridge and fails when its harness blocks the SDK. Its failure log is retained as a harness maintenance gap. A current v2-fixture probe separately verifies English/Russian/fallback detection, dictionary parity and Cyrillic rendering; do not interpret the old suite as passing.
