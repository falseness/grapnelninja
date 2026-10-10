# Current Y8 inspection kit

TASK-270 refreshes `artifacts/y8-release/` and
`artifacts/y8-submission-kit.zip` from the TASK-267 candidate verified by
TASK-268. This supersedes the historical release-directory claims in
Y8-RELEASE.md and Y8-MEDIA-HANDOFF.md. Runtime build:
`2026-10-10-y8-candidate267`, source
`d858abc8a755d071ee79b76d35e3667bee10e981`, game ZIP SHA256
`c96a029eaff51071ea0bab0d260981dd14c0c91629097d49784e812eda01bc12`.

The kit is prepared for local inspection. TASK-265 remains autoskip with six
unresolved measured performance regressions. TASK-270's requirement that all
required local checks pass is therefore unsatisfied; it must remain pending.
Package readiness, submission readiness, upload and moderation approval are
false. Fixing that inherited rendering gate is outside this assembly task.
Reduced-resolution FPS gains do not establish equal-quality optimization gains.
Native phones, hardware/interactive DevTools checks, hosted preview/ads,
console slots, upload and moderation remain owner checks, NOT PERFORMED.

The kit includes the exact tested game ZIP, six covers, three screenshots and
reviewed owner/listing/reviewer instructions. Media keeps its historical
TASK-263 capture provenance. It excludes raw QA, source frames and unrelated
output. Workspace evidence references in manifest.json are explicitly external;
they are not payloads for upload. Only the inner game ZIP is a future game
upload, after the unresolved local gate and owner checks are addressed.

`python3 tools/assemble_y8_submission.py` assembles once and preserves previous
release bytes under `artifacts/TASK-270/previous-release/`. Historical manifests
are never rewritten. `historical-relocations.json` maps the old mutable release
references to their saved byte-identical files. Earlier audits that directly
follow the mutable alias must use this relocation map after assembly.

`python3 tools/assemble_y8_submission.py --audit` checks archive CRCs, full
inventories, current/committed/tested runtime identity, all sealed evidence
hashes, handoff references and readiness consistency without running browsers.
Exit zero means integrity, not performance recovery. `--require-ready` also
enforces the local gate and must fail while the recorded regressions persist.
Both results are retained as command/exit-coded evidence. Use a new evidence
run for future changes; do not overwrite failed attempts or their manifests.
