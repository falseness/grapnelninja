# Playgama upload handoff (TASK-249)

On 2026-10-09, authenticated MCP access succeeded on two fresh connections with
the same configuration and organization. The current release and three reviewed
TASK-247 covers were uploaded to existing application
`cmuu1nvs30d00hj0h49c07spq` (Grapnel Ninja). Earlier access-blocked notes are
historical; do not repeat consent or upload these files again.

The uploaded ZIP is the prepared source `2fd723fd07e2ef81d9c4a22fee65a5368923eecc`
release, 104899 bytes, SHA-256
`cd4611f8d3dc53aba7294bc9b1ed711d6336df91ba2c7a3e75d73937a69a4909`.
Every ZIP entry matched both that committed source and the pre-upload HEAD.
Archive `cmv0qbs6c004joj0i8tc458gp` returned processing `DONE`, state `PASSED`,
Bridge `FOUND`, version `2.3.1`. This is processing acceptance, not moderation
approval or full hosted QA certification.

| Cover | Confirmed and read-back media ID |
| --- | --- |
| Square, 800×800 | `cmv0qbt4h002uqm0hspumkuck` |
| Portrait, 1080×1920 | `cmv0qbv21004moj0iofftupwe` |
| Landscape, 1920×1080 | `cmv0qbwzz0032qm0ha745qaqb` |

Before/after comparison preserves all unrelated listing fields, all four older
archives and the existing active sandbox archive. Only archives, media,
coverImage, checksum and updatedAt changed. The form remains `REJECTED`;
no moderation submission, sandbox publication, campaign or application creation
was performed. Listing text remains unchanged, including its older rewarded-ad
description; this upload does not certify listing accuracy.

TASK-249 remains **pending**. Screenshot replacement and native listing captures
are incomplete. The supported MCP tools provide no screenshot upload operation;
an authenticated developer-console browser session is still needed. The public
QA page opens without console authentication, but it is not a listing capture.

In the existing application's console, replace the screenshot set with
`main-01.png`, `main-02.png`, `main-04.png`, and `main-10.png` from
`artifacts/TASK-249/upload-20261009T085213Z/selected-screenshots.zip`.
These are individually reviewed, real TASK-247 gameplay captures, 1280×720;
their source hashes and fixture limitations are recorded in
`screenshot-selection.json`. Save the screenshot changes, then capture the native
listing showing all three cover orientations and the four screenshots. Read back
the screenshot media IDs and compare all unrelated fields again. Do not submit
moderation or start a campaign as part of this remaining step.

Sanitized receipts, exact source mappings, two-connection access proof,
before/after records, checklist review and independent evidence inspection live
under `artifacts/TASK-249/upload-20261009T085213Z/`. Root `remote-before.json`,
`remote-after.json`, `upload-receipts.json`, `manifest.json` and `verifier.log`
refer to this run. Previous root evidence is preserved in this run's `prior-root/`.
No credentials or signed upload URLs are retained.

The returned [QA link](https://developer.playgama.com/qa-tool/cmv0qbs6c004joj0i8tc458gp)
loads the new build and reports `game_ready`, but also reports:
“Bridge config passed to initialize() as an external URL instead of a path to
playgama-bridge-config.json”. The screenshot and text are in `qa-entry.png` and
`qa-entry.json`. Investigate this during hosted QA; it is not a green QA result.
The pre-upload checklist additionally records the localStorage fallback/journal
deviation, unverified physical-device/full-playthrough checks and missing product
telemetry. The user-required exact release was preserved.

After the console step, rerun independent evidence inspection and all four
TASK-249 test steps. Mark `to-verify` only when the missing screenshot receipts and
native listing captures actually pass. No later ticket is a prerequisite. Never
commit `artifacts/` or `screenshots/`; leave itch deliverables unchanged.
