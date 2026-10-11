# Current Y8 inspection kit

TASK-285 (2026-10-11) rebuilds `artifacts/y8-release/` and
`artifacts/y8-submission-kit.zip` from the current committed runtime with
`python3 tools/y8_package.py` (subcommands `build`, `functional`, `media`,
`readiness`, `assemble`, `package-check`, `manifest`; see its docstring). The
current package identity (source revision, build tag, ZIP SHA256) is in
`artifacts/y8-release/manifest.json`; the runtime build tag is
`2026-10-11-y8-candidate285`. The previous TASK-270 kit is preserved under
`artifacts/TASK-285/previous-release/` and `previous-submission-kit.zip`.

What the TASK-285 kit does and does not claim:

- The five offline browser suites (release, embed, mobile-embed, lifecycle,
  ads) were re-run against the exact new ZIP; the nine media assets were
  recaptured from it and compared pixel-wise with the TASK-263 captures.
  `artifacts/TASK-285/readiness.json` keeps functional package preparation,
  software regression status, native 60-FPS acceptance, submission readiness
  and moderation status as separate fields.
- Performance did not succeed: TASK-282 measured the integrated runtime faster
  than the frozen TASK-271 control in every cell but still about twice the
  frame time of the original ZIP on the software renderer, and every TASK-284
  native row is UNVERIFIED (no owner results). `60fps_achieved` and
  `submission_ready` stay false; nothing was uploaded or submitted.
- Historical TASK-265/270 statuses are recorded as evidence, not used as
  hardcoded blockers; the readiness evaluation uses current evidence only.
- WebKit was not available in the TASK-285 environment (binary removed for
  disk space; reinstall failed with ENOSPC, log preserved), so the release
  suite ran on Chromium and Firefox; `tools/verify_y8_release.py` honours a
  `Y8_ENGINES` override and the omission is recorded in release-checks.json.

The sections below describe the superseded TASK-270 kit.

# TASK-270 inspection kit (superseded)

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

The original assembly preserved previous release bytes under
`artifacts/TASK-270/previous-release/`. Historical manifests remain unchanged;
`historical-relocations.json` maps replaced aliases to their saved bytes. The
saved integrity PASS is reusable while runtime, candidate and evidence stay
unchanged. It is not a performance recovery result. Default assembly now requires
explicit inputs and fresh output paths, described below.

TASK-270 readiness tooling now evaluates explicit immutable inputs. The finite
old/new offline comparison is recorded in
`artifacts/TASK-270/evaluator-experiment/`; its synthetic fixtures test logic,
not FPS recovery or release acceptance. Do not repeat that experiment or the
unchanged package checks as a new implementation attempt. The saved real six
failures still block local readiness; TASK-265 owns the remaining rendering work.

For a genuinely changed candidate and passing upstream evidence, create a
selection JSON with schema 1 and relative, SHA256-bound references named
`candidate`, `tasks`, `performance`, and `local_checks`. `tasks` contains exactly
TASK-252–269 in order, with the current full task objects. `identity` contains
`source_revision` and `archive_sha256` matching the selected candidate. The
candidate's `archive` resolves inside the input directory. The performance JSON
uses the existing matched-density gate schema, with twelve raw sample sets:
three controls and three candidate repetitions for each emulation mode. Each
candidate repetition must match the control settings and source, meet its
relative FPS requirement, and meet the 55-average/30-window absolute thresholds
when the corresponding control qualifies. Stored PASS labels do not determine
readiness. A changed source requires matching measurement evidence.

`local_checks` has the same identity and a `checks` mapping covering every
`TASK-NNN:acceptance_criteria:index` and `TASK-NNN:test_steps:index` obligation.
Each entry binds the exact requirement text with `requirement_sha256` and a
hash-bound `receipt`. Receipts include the same identity, argv, start/end UTC,
exit code, a hash-bound log and nonempty named `assertions` with actual/expected
values. These must describe the actual check outcomes, not just audit completion
or a PASS string. Existing historical evidence needs a current applicability
review and source binding; a done task alone supplies neither. Local review of
owner-check documentation can pass while the owner checks themselves remain
NOT PERFORMED. Set `owner_checks` to the complete list in `y8_readiness.OWNER`,
all NOT PERFORMED; submission, upload and moderation remain false.

Use `python3 tools/assemble_y8_submission.py --inputs <selection.json> --out
<fresh-artifacts-run> --release <fresh-artifacts-release> --kit
<fresh-artifacts-kit.zip>`. All output locations must be absent and within
artifacts/. The assembler refuses failing or synthetic inputs before assembly,
copies cited inputs into the new run, and propagates the evaluated local verdict
through readiness, requirements, manifest, test results and handoff. Existing
release aliases and failed attempts are preserved. Audit the new snapshot using
the same out/release/kit arguments and `--require-ready` only after real upstream
evidence changes. `--audit` checks its recorded source and immutable task state;
a new task state requires a new evaluation. `--package-check` additionally
checks current runtime identity. Use `--history <relocations.json>` for preserved
historical aliases or captured dirty source; every relocation must match the
recorded digest. Integrity acceptance remains separate from local readiness.
