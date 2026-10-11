// TASK-281 candidate: skip the cave-background tile-copy rows that cannot change the image
// (page-injected for the experiment; the body between the BEGIN/END markers is what an ACCEPT
// appends to render/effects.js after class BackgroundRenderer).
//
// Target (TASK-273/274/277, sealed): the cave background is the largest measured cost outside the
// glow composite, 15.9 ms (Main) / 24.8 ms (Chill) of a ~100 ms frame = 24 % at dpr1, as six full-frame
// passes at backing resolution per frame: clear, base gradient, far crystal tile copy, haze gradient,
// near rock tile copy, vignette gradient (TASK-277 cache-profile: visible tile px per frame = exactly
// 2 x backing; 0 tile/gradient rebuilds in steady state, so nothing is reconstructed per frame).
// TASK-279 tested REUSE of the far stack (REJECT: Chromium gradient dither phase under translation,
// bad-mode transform drift). This candidate does not cache or move anything: every pass is submitted
// exactly as today (same order, same gradients, same clear, same Math.random draws); only the pixel
// updates of the two tile copies that provably have no effect go:
//   The far crystal and near rock tiles are painted on transparent canvases with crystals/rocks
//   anchored at the top and bottom edges (paintCrystalTile/paintNearTile), so a band of rows in the
//   middle holds only fully transparent texels. Under source-over a transparent source leaves the
//   destination unchanged, so each copy is clipped to the device rows whose bilinear footprint can
//   touch a non-transparent texel: content row runs mapped to device rows, padded by two texels plus
//   two device pixels, merged, integer-aligned, and extended far beyond the canvas horizontally so no
//   clip edge meets a copy edge. A partially covered clip-edge pixel sees a transparent source and
//   stays exact as well (dst*(1-c) + dst*c). The clip is a Path2D inside one save/restore pair, so
//   the context's current default path and the rest of its state are left exactly as the shipped
//   code leaves them.
// The content rows are read once per tile build (one getImageData alpha scan, cached on the layer
// object next to the tile canvas); there is no per-frame readback.
// Smoke history (artifacts/TASK-281/smoke): an earlier variant also skipped the clearRect under the
// opaque base gradient; it was exact in Chill but changed 1-2 LSB on world edges in Main after ~100
// frames while the background itself stayed exact, with or without the row clip. A full-canvas
// clearRect is therefore not a pure no-op in Chromium when the bad-mode transform has drifted
// (it evidently re-applies the stored matrix), so the clear is kept and only the rows are clipped.
(() => {
// BEGIN TASK-281 candidate body
// Background tile-copy rows whose texels are all transparent are clipped away
// (source-over with a transparent source leaves the destination unchanged). Content
// rows are read once per tile build; the copies keep their submissions and order.
(() => {
 const P = BackgroundRenderer.prototype
 // Row runs [start, end) holding at least one texel with alpha > 0, from RGBA data
 const contentRowRuns = (data, width, height) => {
  const runs = []
  let start = -1
  for (let y = 0; y < height; ++y) {
   let any = false
   for (let i = y * width * 4 + 3, end = (y + 1) * width * 4; i < end; i += 4)
    if (data[i]) { any = true; break }
   if (any) { if (start < 0) start = y }
   else if (start >= 0) { runs.push([start, y]); start = -1 }
  }
  if (start >= 0) runs.push([start, height])
  return runs
 }
 // Device-row bands [y0, y1) (integers, disjoint, sorted) covering every texel row of
 // the runs plus pad: texel row r of the copy sits at device y = top + r * texel
 const deviceBands = (runs, top, texel, pad) => {
  const bands = []
  for (const [r0, r1] of runs) {
   const y0 = Math.floor(top + r0 * texel) - pad, y1 = Math.ceil(top + r1 * texel) + pad
   const last = bands[bands.length - 1]
   if (last && y0 <= last[1]) last[1] = Math.max(last[1], y1)
   else bands.push([y0, y1])
  }
  return bands
 }
 // Bilinear footprint: two texels (in device px, at least one px each) plus two device px
 const bandPad = texel => Math.ceil(2 * Math.max(texel, 1)) + 2
 P.getLayerContentRows = function(layer) {
  const canvas = layer.canvas
  if (layer.contentRows && layer.contentRows.canvas === canvas)
   return layer.contentRows
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
  const runs = contentRowRuns(data, canvas.width, canvas.height)
  const contentRowCount = runs.reduce((n, r) => n + r[1] - r[0], 0)
  layer.contentRows = {canvas, runs, rows: canvas.height, columns: canvas.width, contentRowCount,
   transparentRows: canvas.height - contentRowCount}
  return layer.contentRows
 }
 P.drawLayerTile = function(layer, width, height, shift, edgeFill) {
  const bounds = this.fillBounds()
  const transform = this.ctx.getTransform()
  const toDevice = x => Math.round(transform.a * x + transform.e)
  const fromDevice = x => (x - transform.e) / transform.a
  const right = bounds.x + bounds.width
  // Clip the copies to the device rows that can receive a non-transparent texel
  const content = this.getLayerContentRows(layer)
  let bands = null
  // Device px per texel row of this copy (1 at dpr1, 4/3 at dpr2 where the tile is capped at 1920x1080)
  const texel = transform.d * height / content.rows
  if (content.transparentRows > 0 && content.runs.length && transform.b === 0 && transform.c === 0 && transform.d > 0)
  {
   bands = deviceBands(content.runs, transform.d * shift.y + transform.f, texel, bandPad(texel))
   const fromDeviceY = y => (y - transform.f) / transform.d
   // A Path2D clip leaves the context's current default path untouched
   const clipPath = new Path2D()
   for (const [y0, y1] of bands)
    clipPath.rect(bounds.x - width, fromDeviceY(y0), bounds.width + 2 * width, fromDeviceY(y1) - fromDeviceY(y0))
   this.ctx.save()
   this.ctx.clip(clipPath)
  }
  if (window.__backgroundRowsObserve)
   window.__backgroundRowsObserve(layer, content, bands, transform, shift, height, bounds, texel)
  let k = Math.floor((bounds.x - shift.x) / width)
  let left = fromDevice(toDevice(shift.x + k * width))

  while (left < right)
  {
   const next = fromDevice(toDevice(shift.x + (k + 1) * width))
   this.ctx.drawImage(layer.canvas, left, shift.y, next - left, height)
   left = next
   ++k
  }
  if (bands)
   this.ctx.restore()

  this.ctx.fillStyle = edgeFill
  if (bounds.y < shift.y)
   this.ctx.fillRect(bounds.x, bounds.y, bounds.width, shift.y - bounds.y)
  if (shift.y + height < bounds.y + bounds.height)
   this.ctx.fillRect(bounds.x, shift.y + height, bounds.width, bounds.y + bounds.height - shift.y - height)
 }
 window.__backgroundRowsCandidate = {task: 'TASK-281', contentRowRuns, deviceBands, bandPad}
})();
// END TASK-281 candidate body
})();
