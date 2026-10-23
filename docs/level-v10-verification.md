# Extended mountain v10

The route keeps its two 80% opening transfers and 150% upward turns. Other
transfers have at least a 200% edge-to-edge gap, with exposed traverses of
300% or more. The opening still goes right, up, then left. Later combinations
continue left to avoid low panels above earlier launch points. Wider rebound
landings separate the following turns from the preceding slopes. A yellow
brake above the final descending flight blocks the tested roof-launch skip.

The canonical design requirements are in
`/root/grapnelninja/artifacts/levels/level-guidelines.md`. Generate from the
preserved concept, then import the SVG; do not edit `leveldata.js` geometry:

```sh
python3 tools/retune_extended_level.py --source artifacts/level/extended-mountain-measurements.json --output-dir artifacts/levels --guidelines artifacts/levels/level-guidelines.md
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output artifacts/levels/extended-mountain.level.json
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output leveldata.js --format javascript
PYTHONPATH=tools python3 -m unittest test_harder_route test_harder_route_replays test_opening_jump_variety test_extended_opening test_retuned_level
```

`test_harder_route_replays` uses recorded mouse events for four continuous
ceiling/slope/rebound combinations, including the production finish trigger.
Together with the opening replay and the remaining local transfer policies,
it covers all 30 transfers. Fixtures start at rest above a panel; gravity
produces their entry velocity. No later position or velocity writes are used.
This is local and connected-sequence evidence, not a complete climb from spawn.

Run the broader shortcut audit with the production 540-unit grapple range:

```sh
python3 tools/audit_level_routes.py --level artifacts/levels/extended-mountain.level.json --output /tmp/v10-shortcuts.json
python3 tools/audit_level_routes.py --level artifacts/levels/extended-mountain.level.json --expanded --sources P18,P25,P28 --output /tmp/v10-expanded.json
python3 tools/audit_opening_releases.py --level artifacts/levels/extended-mountain.level.json --inputs tools/fixtures/harder-opening-inputs.json --output /tmp/v10-releases.json
```

The audit tests all non-successors inside its stated spatial envelope, reports
excluded pairs, and treats later contacts, attachments, and premature completion
as bypasses. Normal policies use 0, 1, 2, 3, 5, and 8 pumps at both ends and the
middle of each panel. Expanded policies vary the last pump aim and entry drop;
the opening audit preserves incoming momentum and varies the ceiling release.
Any demonstrated skip fails, including previously existing skips. Finite input
samples do not prove that every possible shortcut has been eliminated.

Authoring files, measurements, audit reports and previews remain under
`artifacts/levels/`; generated artifacts and screenshots are not committed.
