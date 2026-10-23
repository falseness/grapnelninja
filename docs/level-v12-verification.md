# Extended mountain v12: longer opening beneath the late leftward route

The first two gaps are 120% and 160% of the 540-unit grapple length:
648 and 864 world units. The mixed rightward combination then uses gaps of
300%, 200%, 200%, and 400%. The ceiling entry and exposed traverse are harder
than v10, while the first two transfers remain gentler than v11.

Eight additional full-size landing structures extend the opening rightward
by approximately 43,980 units, with alternating rises, drops and exposed
transfers. Their gaps alternate between 250%, 300%, and 350%. The upper route
moves with the new departure, so its late left-hand section sits above earlier
terrain. The upward transfer remains 150%. The level has 39 panels and 38
transfers. The wider descending slope also catches the tested flights that
previously skipped that landing.

Gravity-only drop tests from the three leftmost late panels land on P6, P5,
and P4 respectively, before the below-spawn reset. This demonstrates recovery
onto earlier terrain, not a checkpoint or a guarantee that every possible
fall misses every gap.

Current guidelines: /root/grapnelninja/artifacts/levels/level-guidelines.md
Current SVG: /root/grapnelninja/artifacts/levels/extended-mountain.svg
Local verification: /root/grapnelninja/artifacts/levels/harder-right/

Generate with the commands in level-v11-verification.md. The runtime bundle
comes from the SVG importer; it is not hand-edited. Yellow obstacles retain
300% green clearance and 100% yellow clearance.

Run the main checks:

```sh
PYTHONPATH=tools python3 -m unittest test_harder_route test_harder_route_replays test_lower_catch_route test_opening_jump_variety test_extended_opening test_retuned_level
```

The recorded opening policy traverses the ceiling, slope, rebound and exposed
jump continuously. Upper combinations use translated recorded inputs. The
added transfers have local policies in harder-transfer-inputs.json.
No position or velocity is injected after the initial replay fixtures.
The probe's optional targetWhenInRange policy coasts before shooting at a
lower destination, avoiding an unintended grapple back onto the departure
platform; it uses ordinary pointer inputs and does not change game physics.

Shortcut checks sample finite input policies and report their spatial scope.
They do not prove global shortcut absence or a complete climb from spawn.
Generated assets and screenshots remain ignored and are not committed.
