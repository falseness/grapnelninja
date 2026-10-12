Combined-support visual gate

Run the frozen TASK-324 trees through each selected browser, sequentially:

    python3 tools/playgama_render_compare.py visuals --control artifacts/TASK-324/control --candidate artifacts/TASK-324/candidate --engine firefox --support-visuals --out <fresh-directory>

Repeat with `--engine chrome` (official Google Chrome, without substitution).
The optional fixtures append to the historical inventory. Each mode covers
startup, manual-clock gameplay, camera translation, overlapping edge lights and
motes, empty support, death overlay, restart with shake, and odd portrait and
landscape resize. These explicit rendering fixtures are not natural input or
performance evidence. The portrait screen intentionally shows the rotation
message and retains a landscape backing canvas.

Retain all failed attempts. Review every control/candidate/difference triplet,
record findings and original paths in visuals/review.json, and seal source,
helper, browser, logs and consumed evidence in manifest.json. Run the read-only
`tools/audit_playgama_support_visuals.py <ticket-directory>` audit. It recomputes
pixels and states and enforces the 3/255 maximum channel tolerance. Any visual
failure requires REJECT; eligibility here never authorizes production adoption.
TASK-325's local audit.py is a copy of that auditor. Evidence stays uncommitted.
