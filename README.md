# grapnelninja
Html 5 konva simple game

Mobile play supports landscape orientation. Portrait shows a rotate prompt and pauses an active run; rotate back and tap Resume to continue.

## Grapple Over: grapnel range

Single grapnel is the intended way to play. Double grapnel mode (pause menu toggle "Grapnel: single / double range") doubles the grapple range as an easier option, both before and after the range upgrade. Switching keeps the run going (position, time and best height); a run that used double range stays marked as such.

## Recording freezes in your own browser (`?visualsPerf=1`)

The server's headless browser has no GPU, so its frame times do not show the
freezes players see. To record them on your own device:

1. Open the game with `?visualsPerf=1` added to the address, e.g.
   `http://<host>:8000/index.html?visualsPerf=1`. A small panel appears in the
   bottom-left corner.
2. Press **Start**, then play until a freeze happens. The panel counts freezes
   (frames over 50 ms), shows the worst one and the slowest layer of the last one.
3. Press **Export**. This stops the recording and downloads
   `visuals-performance.json`. Send that file for analysis.

Without the flag nothing is recorded and no panel is shown. Nothing is sent
anywhere; the file stays on your device until you send it. `?visualsPerf=1`
can be combined with `?perf=1`.
