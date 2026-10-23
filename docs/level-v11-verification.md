# Extended mountain v11: harder opening

The first two edge-to-edge gaps increase from 80% / 80% to 160% / 240%
of the 540-unit grapple length (864 and 1,296 world units). Neither transfer
allows reaching the next panel while stationary on the departure panel.
The opening panel shapes stay full-size. P2 and the subsequent mixed ceiling,
descent and rebound route move together; their relative geometry is unchanged.
The 150% upward-turn targets and yellow clearance rules remain in force.

The canonical requirements are in
/root/grapnelninja/artifacts/levels/level-guidelines.md.
The preserved source remains /root/grapnelninja/artifacts/level/.
Current generated SVG, measurements and imported bundles live in
/root/grapnelninja/artifacts/levels/.

Generate and verify:

```sh
python3 tools/retune_extended_level.py --source artifacts/level/extended-mountain-measurements.json --output-dir artifacts/levels --guidelines artifacts/levels/level-guidelines.md
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output artifacts/levels/extended-mountain.level.json
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output leveldata.js --format javascript
PYTHONPATH=tools python3 -m unittest test_harder_route test_harder_route_replays test_opening_jump_variety test_extended_opening test_retuned_level
python3 tools/audit_level_routes.py --level artifacts/levels/extended-mountain.level.json --sources P0,P1,P2 --output artifacts/levels/harder-start/shortcuts.json
```

The opening and upper recorded inputs are translated with the unchanged
combinations, then replayed with production physics. The P16 replay also
shifts its aim by 0.001 units left to avoid a tangent-sensitive launch after
the imported coordinates are rounded; its successful replay is reverified. The two new transfers
use independently found release policies recorded in harder-transfer-inputs.json.
These policies start with gravity-produced velocity, not injected velocity.
They establish local reachability, not a complete uninterrupted climb from spawn.
Shortcut audits cover finite policies within a stated spatial envelope;
they do not establish global shortcut absence.
