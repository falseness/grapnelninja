# Reproducible Playgama release

Build only from a pinned commit reachable on `playgama2`:

```sh
python3 tools/build_playgama.py --revision <full-commit-id> --out artifacts/TASK-248
unzip -t artifacts/TASK-248/grapnelninja-playgama.zip
sha256sum artifacts/TASK-248/grapnelninja-playgama.zip
python3 tools/build_playgama.py --revision <full-commit-id> --out artifacts/TASK-248/rebuild
cmp artifacts/TASK-248/grapnelninja-playgama.zip artifacts/TASK-248/rebuild/grapnelninja-playgama.zip
python3 tools/smoke_playgama_archive.py --zip artifacts/TASK-248/grapnelninja-playgama.zip --out artifacts/TASK-248
python3 tools/verify_playgama_release.py --out artifacts/TASK-248
```

Use fresh output directories: the builder refuses to replace an existing archive.
The builder reads Git blobs, not working files. It includes `index.html`, its local
script/style references, and the Bridge config. The current application synthesizes
its audio and renders its visuals in code; there are no external media assets.
The hosted Bridge SDK URL stays in the HTML. New dynamically fetched assets must
be added to the builder and exercised by the isolated smoke test.

ZIP names are sorted, timestamps and permissions fixed, compression level explicit.
Reproduction uses Python's zipfile/zlib; versions are recorded in the manifest.
The inventory records both SHA-256 and Git blob identity for every runtime file.
No test tools, screenshots, documentation, output or evidence belong in the ZIP.

Smoke testing requires the repository's Playwright Chromium installation. It serves
only a temporary ZIP extraction under `/nested/game/release/`, checks every runtime
request, exercises both modes with mouse and emulated touch, and measures actual
WebAudio samples before mute, during mute and after restore. Captures are unedited,
native-resolution browser PNGs. Normal and rejected Bridge initialization use the
existing SDK fixture at the network boundary. This is local release validation;
physical devices and the live portal remain untested. No later task is required.
