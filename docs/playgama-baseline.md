# Published Playgama baseline

The local `playgama-start-firefox` repair branch starts at
`a570592a1a52b9af0278efa7583874ae25419d0d` (Declare UTF-8 before bundled
game scripts), imported from `/opt/grapnelninja`. Master remains at
`b72ff27120656518282e7196de32aaa2a0e8f035`. Preserve subsequent repair
commits when reusing this branch.

Verify the published archive without launching the game or contacting any
external service:

```sh
git merge-base --is-ancestor a570592a1a52b9af0278efa7583874ae25419d0d HEAD
python3 tools/verify_playgama_baseline.py \
  --archive /opt/grapnelninja/artifacts/loading2/release-final/grapnelninja-playgama.zip \
  --out artifacts/TASK-287/archive-check.json
```

The expected archive SHA256 is
`78473df0ecdb9f959351c517cc60c10c141a1e451ac03ac10232425a29ef88c7`.
The verifier loads the historical builder from Git, obtains first-party
runtime files from that commit, and calls its original `bundle` and
`archive` functions. It checks ZIP CRCs, exact member inventory, member
bytes, and the complete rebuilt ZIP. It does not require a local
`playgama2` branch. The report retains both actual and expected hashes.

TASK-287 evidence is local under `artifacts/TASK-287/`. Task-list and
progress hashes in `baseline.json` describe branch preparation, before
the required task-status update and progress append. `progress.md` already
existed and was not created by preparation. Neither artifacts nor
screenshots belong in this task's commit.

When resuming preparation, verify ancestry instead of requiring `HEAD` to
equal the baseline: the branch may already contain repair commits. Record
its tip before and after preparation and require those tips to match.

The initial preservation audit observed concurrent changes in
`/opt/grapnelninja`. That failed attempt is retained under
`artifacts/TASK-287/prior-attempt/`. The subsequent preparation and archive
verification passed the full recursive preservation check (mode, size,
mtime and ctime; access times excluded). See `baseline.json` and the
`opt-before.json` / `opt-after.json` inventories for the measured interval.
No task writes were made to the reference checkout.

Environment discovery found Python 3.10.12 (`python3`; no `python` alias),
Playwright 1.60.0 (`python3 -m playwright`), and cached Chromium, Firefox,
and WebKit on Ubuntu 22.04.5. This ticket validates baseline provenance
only: browser functionality, graphics behavior, performance, and native
devices remain UNVERIFIED. Future runtime tests must isolate production
analytics and ads. Treat `/opt/grapnelninja` as a read-only reference.
