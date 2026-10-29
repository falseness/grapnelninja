"""Freeze attribution in the ?visualsPerf=1 recorder (render/visualsperf.js, TASK-775/776).

Headless Chromium has no GPU, so this checks structure and labels, never
absolute timings. Every stall is injected by this test through
page.evaluate, never by shipped code:

- busy: a 300 ms synchronous loop inside one frame must give a freeze whose
  mainThreadSilenceMs (longest time without a heartbeat) is >= 250;
- idle: one requestAnimationFrame is routed through setTimeout(300) while the
  main thread stays idle, so the freeze has gapMs >= 250 but
  mainThreadSilenceMs < 50;
- heap: Chromium runs with --enable-precise-memory-info; ~50 MB of arrays are
  allocated and dropped, and samples must carry heapMB (a sample-to-sample
  drop >= 2 MB is reported when the collector ran inside the window);
- teardown: after stop() the heartbeat beat count stays put for 500 ms and
  the long-animation-frame observer is disconnected;
- freeze windows: with start({ringSize: 100}) and a busy stall after frame
  300 of >= 600, the stall's freezeWindows entry still has 30 samples before
  and 30 from the freeze on, although the ring dropped those frames;
- live canvases: over a >= 20 s play session samples carry liveCanvasMB
  about once per second, > 0, never below the first value after warm-up;
- hashes: one sha256 per loaded script, equal to the file on disk, and
  buildId recomputed here; from file:// every script fails on its own
  (Chrome's fetch has no file scheme), which was the TASK-776 user report.

Set VISUALSPERF_ATTRIBUTION_EVIDENCE_DIR=<dir> to write stalls.json,
export-normal.json (a plain recording), windows.json, canvasmem.json and
hashes.json there.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import unittest

from browser_test_support import start_browser_test, wait_for_boot

ROOT = Path(__file__).resolve().parent.parent
# Small, so a headless frame's own work stays well under the idle bound
VIEWPORT = {'width': 320, 'height': 180}
STALL_MS = 300

# Test-only: records every PerformanceObserver's observed types and whether it
# is still connected
OBSERVER_SPY = '''(() => {
    const proto = PerformanceObserver.prototype, observe = proto.observe, disconnect = proto.disconnect
    window.__observers = []
    proto.observe = function(options) {
        if (!window.__observers.includes(this))
            window.__observers.push(this)
        this.__types = (this.__types || []).concat([options.type])
        this.__connected = true
        return observe.apply(this, arguments)
    }
    proto.disconnect = function() {
        this.__connected = false
        return disconnect.apply(this, arguments)
    }
})()'''

BUSY = '''ms => requestAnimationFrame(() => {
    const end = performance.now() + ms
    while (performance.now() < end) {}
})'''

# The game loop's next frame comes from a timer instead of the display
IDLE = '''ms => {
    const raf = window.requestAnimationFrame
    window.requestAnimationFrame = function(callback) {
        window.requestAnimationFrame = raf
        return setTimeout(() => callback(performance.now()), ms)
    }
}'''

FRAMES = 'n => new Promise(r => { const f = () => --n ? requestAnimationFrame(f) : r(); requestAnimationFrame(f) })'


def evidence_dir():
    path = os.environ.get('VISUALSPERF_ATTRIBUTION_EVIDENCE_DIR')
    if not path:
        return None
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def freeze_fields(freeze):
    keys = ['t', 'gapMs', 'rafLagMs', 'mainThreadSilenceMs', 'unaccountedMs', 'heapBeforeMB',
            'heapAfterMB', 'heapDropMB', 'slowestLayer']
    out = {k: freeze.get(k) for k in keys}
    out['loafs'] = freeze['context']['loafs']
    return out


class VisualsPerfAttributionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback,
                                                  chromium_args=['--enable-precise-memory-info'])
        cls.evidence = evidence_dir()
        cls.stalls = {}

    @classmethod
    def tearDownClass(cls):
        if cls.evidence and cls.stalls:
            (cls.evidence / 'stalls.json').write_text(json.dumps(cls.stalls, indent=1) + '\n')
        cls.stack.close()

    def open(self, start='{}', url=None):
        context = self.browser.new_context(viewport=VIEWPORT)
        self.addCleanup(context.close)
        context.add_init_script(OBSERVER_SPY)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(url or self.url + 'index.html?visualsPerf=1', wait_until='load')
        wait_for_boot(page)
        page.evaluate(f'visualsPerf.start({start})')
        page.evaluate(FRAMES, 30)
        return page

    def stop(self, page):
        report = page.evaluate('visualsPerf.stop()')
        self.assertEqual(report['schemaVersion'], 3)
        return report

    def stall_freeze(self, report, injected_at):
        after = [f for f in report['freezes'] if f['t'] > injected_at]
        self.assertTrue(after, 'no freeze after the injected stall')
        return max(after, key=lambda f: f['gapMs'])

    def test_busy_stall(self):
        page = self.open()
        injected_at = page.evaluate('performance.now()')
        page.evaluate(BUSY, STALL_MS)
        page.evaluate(FRAMES, 20)
        report = self.stop(page)
        freeze = self.stall_freeze(report, injected_at)
        self.__class__.stalls['busy'] = freeze_fields(freeze)
        print('BUSY', json.dumps(freeze_fields(freeze)), flush=True)
        self.assertGreaterEqual(freeze['gapMs'], STALL_MS)
        self.assertGreaterEqual(freeze['mainThreadSilenceMs'], 250)
        if report['loafSupported']:
            self.assertTrue(any(e['duration'] >= STALL_MS for e in freeze['context']['loafs']),
                            freeze['context']['loafs'])
        print(f'PASS busy: gapMs={freeze["gapMs"]:.1f} mainThreadSilenceMs={freeze["mainThreadSilenceMs"]} '
              f'loafs={len(freeze["context"]["loafs"])}', flush=True)

    def test_idle_stall(self):
        page = self.open()
        injected_at = page.evaluate('performance.now()')
        page.evaluate(IDLE, STALL_MS)
        page.evaluate(FRAMES, 20)
        report = self.stop(page)
        freeze = self.stall_freeze(report, injected_at)
        self.__class__.stalls['idle'] = freeze_fields(freeze)
        print('IDLE', json.dumps(freeze_fields(freeze)), flush=True)
        self.assertGreaterEqual(freeze['gapMs'], 250)
        self.assertLess(freeze['mainThreadSilenceMs'], 50)
        print(f'PASS idle: gapMs={freeze["gapMs"]:.1f} mainThreadSilenceMs={freeze["mainThreadSilenceMs"]}',
              flush=True)

    def test_heap_fields(self):
        page = self.open()
        for attempt in range(3):
            page.evaluate('v => { window.__junk = Array.from({length: 50}, () => new Array(131072).fill(v)) }',
                          attempt + 0.5)
            page.evaluate(FRAMES, 5)
            page.evaluate('() => { delete window.__junk }')
            page.wait_for_timeout(1500)
        report = self.stop(page)
        samples = report['samples']
        with_heap = [s for s in samples if 'heapMB' in s]
        heap = [s['heapMB'] for s in with_heap]
        drops = [round(a - b, 1) for a, b in zip(heap, heap[1:]) if a - b >= 2]
        share = len(with_heap) / len(samples)
        for f in report['freezes']:
            for key in ('heapBeforeMB', 'heapAfterMB', 'heapDropMB'):
                self.assertIn(key, f)
            self.assertGreaterEqual(f['heapDropMB'], 0)
        result = {'samples': len(samples), 'samplesWithHeapMB': len(with_heap), 'share': round(share, 4),
                  'minHeapMB': min(heap), 'maxHeapMB': max(heap), 'dropsGe2MB': drops,
                  'freezesWithHeapFields': sum('heapDropMB' in f for f in report['freezes']),
                  'freezes': len(report['freezes']),
                  'note': 'collector ran inside the window' if drops else
                  'headless never collected inside the window; heapMB present on the samples'}
        if report['freezes']:
            worst = max(report['freezes'], key=lambda f: f['heapDropMB'])
            result['largestHeapDropFreeze'] = freeze_fields(worst)
        self.__class__.stalls['heap'] = result
        print('HEAP', json.dumps(result), flush=True)
        self.assertGreaterEqual(share, 0.95)
        self.assertTrue(drops or share >= 0.95)
        self.assertGreaterEqual(max(heap) - min(heap), 40, 'the ~50 MB allocation is not visible')
        print(f'PASS heap: heapMB on {len(with_heap)}/{len(samples)} samples, drops >= 2 MB: {drops}', flush=True)

    def test_normal_export_keys(self):
        page = self.open()
        page.evaluate(FRAMES, 60)
        report = self.stop(page)
        for key in ('loafSupported', 'loafs', 'heartbeat', 'heartbeatMs'):
            self.assertIn(key, report)
        self.assertTrue(report['loafSupported'])
        self.assertLessEqual(len(report['loafs']), 2000)
        for e in report['loafs']:
            self.assertEqual(set(e), {'startTime', 'duration', 'blockingDuration', 'renderStart',
                                      'styleAndLayoutStart', 'scripts'})
            self.assertLessEqual(len(e['scripts']), 3)
            for s in e['scripts']:
                self.assertEqual(set(s), {'sourceURL', 'sourceFunctionName', 'invoker', 'duration'})
        for s in report['samples']:
            self.assertIn('rafLagMs', s)
            self.assertIn('heapMB', s)
        for f in report['freezes']:
            for key in ('mainThreadSilenceMs', 'heapBeforeMB', 'heapAfterMB', 'heapDropMB', 'rafLagMs'):
                self.assertIn(key, f)
            self.assertIn('loafs', f['context'])
            self.assertIsInstance(f['context']['liveCanvases'], int)
            self.assertGreater(f['context']['liveCanvasMB'], 0)
            self.assertLessEqual(f['mainThreadSilenceMs'], f['gapMs'] + 0.1)
        if self.evidence:
            (self.evidence / 'export-normal.json').write_text(json.dumps(report, indent=1) + '\n')
        print(f'PASS export: schemaVersion 3, {len(report["samples"])} samples with rafLagMs/heapMB, '
              f'{len(report["freezes"])} freezes with attribution fields, {len(report["loafs"])} loafs', flush=True)

    def test_stop_teardown(self):
        page = self.open()
        running = page.evaluate('''() => ({beats: visualsPerf.beats,
            loaf: __observers.filter(o => o.__types.includes("long-animation-frame") && o.__connected).length})''')
        self.assertGreater(running['beats'], 0)
        self.assertEqual(running['loaf'], 1)
        page.evaluate('visualsPerf.stop()')
        before = page.evaluate('visualsPerf.beats')
        page.wait_for_timeout(500)
        after = page.evaluate('''() => ({beats: visualsPerf.beats,
            loaf: __observers.filter(o => o.__types.includes("long-animation-frame")).map(o => o.__connected)})''')
        self.assertEqual(after['beats'], before)
        self.assertEqual(after['loaf'], [False])
        print(f'PASS teardown: beats {before} -> {after["beats"]} over 500 ms after stop(); '
              f'long-animation-frame observer connected={after["loaf"]}', flush=True)

    def write(self, name, data):
        if self.evidence:
            (self.evidence / name).write_text(json.dumps(data, indent=1) + '\n')

    def test_freeze_windows(self):
        page = self.open('{ringSize: 100}')
        page.evaluate(FRAMES, 300)
        injected_at = page.evaluate('performance.now()')
        page.evaluate(BUSY, STALL_MS)
        page.evaluate(FRAMES, 300)
        report = self.stop(page)
        frames = len(report['samples']) + report['droppedSamples']
        freeze = self.stall_freeze(report, injected_at)
        index = report['freezes'].index(freeze)
        windows = [w for w in report['freezeWindows'] if w['freezeIndex'] == index]
        self.assertEqual(len(windows), 1, 'no window for the stall freeze')
        window = windows[0]
        samples = window['samples']
        result = {'frames': frames, 'ringSize': report['ringSize'], 'ringSamples': len(report['samples']),
                  'droppedSamples': report['droppedSamples'], 'droppedWindows': report['droppedWindows'],
                  'freezes': len(report['freezes']), 'freezeWindows': len(report['freezeWindows']),
                  'stallFreeze': {'index': index, 't': freeze['t'], 'gapMs': freeze['gapMs']},
                  'window': {'freezeIndex': window['freezeIndex'], 'freezeAt': window['freezeAt'],
                             'length': len(samples), 'before': window['freezeAt'],
                             'after': len(samples) - window['freezeAt'],
                             'firstT': samples[0]['t'], 'lastT': samples[-1]['t'],
                             'freezeSampleT': samples[window['freezeAt']]['t']},
                  'oldestRingT': report['samples'][0]['t']}
        self.write('windows.json', result)
        print('WINDOWS', json.dumps(result), flush=True)
        self.assertGreaterEqual(frames, 600)
        self.assertGreater(report['droppedSamples'], 0)
        self.assertEqual(len(samples), 60)
        self.assertEqual(window['freezeAt'], 30)
        self.assertEqual(samples[30]['t'], freeze['t'])
        self.assertEqual([s['t'] for s in samples], sorted(s['t'] for s in samples))
        # The ring no longer holds these frames
        self.assertLess(samples[-1]['t'], report['samples'][0]['t'])
        for w in report['freezeWindows']:
            self.assertLessEqual(len(w['samples']), 60)
        print(f'PASS windows: {frames} frames, droppedSamples={report["droppedSamples"]}, stall window '
              f'{len(samples)} samples (30 before, 30 from the freeze), t {samples[0]["t"]:.1f}..'
              f'{samples[-1]["t"]:.1f} < oldest ring t {report["samples"][0]["t"]:.1f}', flush=True)

    def test_live_canvas_mb(self):
        page = self.open()
        started = page.evaluate('performance.now()')
        box = page.viewport_size
        # A play session: run right, throw the grapnel now and then
        page.keyboard.down('ArrowRight')
        for i in range(21):
            page.mouse.click(box['width'] * (0.55 + 0.04 * (i % 5)), box['height'] * (0.2 + 0.05 * (i % 3)))
            page.wait_for_timeout(1000)
        page.keyboard.up('ArrowRight')
        report = self.stop(page)
        series = [{'t': round(s['t'] - started, 1), 'liveCanvasMB': s['liveCanvasMB']}
                  for s in report['samples'] if 'liveCanvasMB' in s]
        values = [s['liveCanvasMB'] for s in series]
        span = (report['samples'][-1]['t'] - report['samples'][0]['t']) / 1000
        gaps = [b['t'] - a['t'] for a, b in zip(series, series[1:])]
        first = values[0]
        result = {'spanS': round(span, 1), 'samples': len(report['samples']), 'withLiveCanvasMB': len(series),
                  'first': first, 'min': min(values), 'max': max(values), 'last': values[-1],
                  'minGapMs': min(gaps), 'maxGapMs': max(gaps),
                  'freezes': [{'t': round(f['t'] - started, 1), 'liveCanvases': f['context']['liveCanvases'],
                               'liveCanvasMB': f['context']['liveCanvasMB']} for f in report['freezes']][:50],
                  'series': series}
        self.write('canvasmem.json', result)
        print('CANVASMEM', json.dumps({k: v for k, v in result.items() if k not in ('series', 'freezes')}),
              flush=True)
        self.assertGreaterEqual(span, 20)
        self.assertGreater(first, 0)
        self.assertGreaterEqual(min(values[1:]), first)
        self.assertGreaterEqual(min(gaps), 1000)
        self.assertGreaterEqual(len(series), span * 0.8)
        for f in report['freezes']:
            self.assertGreater(f['context']['liveCanvases'], 0)
        print(f'PASS canvas memory: {len(series)} samples with liveCanvasMB over {span:.1f} s, '
              f'{first} -> {values[-1]} MB (min {min(values)})', flush=True)

    def hashes(self, page):
        page.wait_for_function('visualsPerf.export().sourceHashFailures !== null')
        return page.evaluate('''() => { const r = visualsPerf.export();
            return {sourceHashes: r.sourceHashes, buildId: r.buildId, sourceHashFailures: r.sourceHashFailures,
                scripts: [...document.scripts].filter(s => s.src).map(s => s.src)} }''')

    def test_source_hashes(self):
        page = self.open()
        result = self.hashes(page)
        paths = [urlparse(src).path for src in result['scripts']]
        hashes = result['sourceHashes']
        self.assertEqual(sorted(hashes), sorted(set(paths)))
        self.assertEqual(result['sourceHashFailures'], 0)
        self.assertRegex(result['buildId'], r'^[0-9a-f]{64}$')
        for path, digest in hashes.items():
            self.assertEqual(digest, hashlib.sha256((ROOT / path.lstrip('/')).read_bytes()).hexdigest(), path)
        lines = sorted(f'{p}:{h}' for p, h in hashes.items())
        self.assertEqual(result['buildId'], hashlib.sha256('\n'.join(lines).encode()).hexdigest())
        self.write('hashes.json', result)
        print(f'PASS hashes: {len(hashes)} scripts hashed (each = sha256 of the file on disk), '
              f'sourceHashFailures=0, buildId={result["buildId"]}', flush=True)

    def test_file_scheme_fails_per_script(self):
        page = self.open(url=(ROOT / 'index.html').as_uri() + '?visualsPerf=1')
        result = self.hashes(page)
        hashes = result['sourceHashes']
        self.assertEqual(len(hashes), len(set(result['scripts'])))
        self.assertEqual(result['sourceHashFailures'], len(hashes))
        self.assertIsNone(result['buildId'])
        for path, entry in hashes.items():
            self.assertEqual(entry['error'], 'TypeError: Failed to fetch', path)
            self.assertTrue(entry['url'].startswith('file://'))
        self.write('hashes-file-scheme.json', result)
        print(f'PASS file://: {len(hashes)} scripts, each its own {{error: TypeError: Failed to fetch}}, '
              f'sourceHashFailures={result["sourceHashFailures"]}, buildId=None', flush=True)


if __name__ == '__main__':
    unittest.main()
