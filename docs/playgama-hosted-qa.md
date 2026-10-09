# Hosted QA handoff (TASK-250)

On 2026-10-09, fresh Chromium desktop and mobile-emulated contexts opened
https://playgama.ai/play/kjkngkpxox successfully. Both observed the game iframe
archive `cmux4zcpp008vl80hrvd8hjhe`. Its public QA page identified the build as
`grapnelninja-playgama-27c7388` and logged `PlaygamaBridge v2.3.1 initialized`
and `[platform] message: game_ready`. No SDK mocks were injected. Mobile was
Chromium iPhone 13 emulation, not a physical device.

This is partial evidence, not a completed release check. The historical
TASK-139 receipt names `cmuuih0ks0igahj0h90vmbtdx`; the available TASK-249
upload receipt list is empty. Neither proves that the currently hosted archive
contains the intended release ZIP. Public QA pages show Login; these were
unauthenticated visits. No authenticated Playgama tool is exposed, local MCP
configuration only lists openaiDeveloperDocs, and plugin discovery returned
no Playgama matches.

TASK-250 remains pending. No sandbox association was changed, replacement app
created, or campaign started. Input, both modes, free restart, storage reload,
audio controls, host pause and interstitial outcomes have not been verified
for the intended upload. Public launch captures alone do not satisfy those checks.

Resume with supported authenticated Playgama access and a receipt binding the
intended ZIP hash to an actual uploaded archive ID. Inspect that archive in QA,
record all required flows and browser/network errors, update the existing
sandbox through supported tooling, read back its association, and repeat the
fresh desktop/mobile hosted flows. Record actual ad availability limitations
without treating an unavailable mandatory check as passed.

Evidence, native captures, source hashes, commands, explicit limitations and
an independent file audit are in `artifacts/TASK-250/`, intentionally untracked.
No later ticket is a prerequisite. Existing itch deliverables are unchanged.
