# Reproducible Playgama release

Build from a pinned commit that descends from the release baseline
`a570592a1a52b9af0278efa7583874ae25419d0d` (UTF-8 declared before bundled scripts).
`<rev>` is the full commit id to ship and `<dir>` a fresh output directory:

```sh
python3 tools/build_playgama.py --revision <rev> --base-revision a570592a1a52b9af0278efa7583874ae25419d0d --out <dir>
python3 tools/build_playgama.py --revision <rev> --base-revision a570592a1a52b9af0278efa7583874ae25419d0d --out <dir>/rebuild
cmp <dir>/grapnelninja-playgama.zip <dir>/rebuild/grapnelninja-playgama.zip
python3 -m zipfile -t <dir>/grapnelninja-playgama.zip
sha256sum <dir>/grapnelninja-playgama.zip
python3 tools/test_playgama_repair_archive.py --zip <dir>/grapnelninja-playgama.zip --out <dir>/suite
python3 tools/verify_playgama_release.py --out <dir>
```

Use fresh output directories: the builder refuses to replace an existing archive.
The builder reads Git blobs, not working files. `bundle()` inlines every plain
`<script src>` of `index.html` in order, so the ZIP has exactly two members:
`index.html` and `playgama-bridge-config.json`. Any other local `src`/`href`
is rejected. The hosted Bridge SDK URL stays external in the HTML. The game
synthesizes its audio and draws its visuals in code; there are no media assets.

`inventory.json` lists the source files read from Git (size, SHA-256, blob id);
`packed-inventory.json` lists the two ZIP members. ZIP names are sorted,
timestamps and permissions fixed, compression level explicit.

`test_playgama_repair_archive.py` serves only the extracted ZIP, fulfils the SDK
locally and blocks other external requests; it runs the readiness, start-flow,
input and packaged telemetry suites and writes
`suite/suite.json`. `verify_playgama_release.py` recomputes `bundle()` from Git
at the recorded revision and checks the ZIP, the rebuild, both inventories and
the suite report. It prints `FAIL: ...` and exits 1 on the first mismatch.

`tools/smoke_playgama_archive.py` predates script inlining and is not part of
this procedure. Physical devices and the live portal remain untested.
