#!/usr/bin/env python3
"""Read a ?visualsPerf=1 export and label each freeze (TASK-777, TASK-786).

    python3 tools/freeze_report.py <recording.json> [--json out.json]

Accepts schemaVersion 1 to 4. Any bytes before the first '{' (a paste
accident, e.g. artifacts/rare_freezes.json, artifacts/new_freezes.json) are
skipped with a warning naming how many. A field the recorder did not have yet
prints as 'unknown'. Hidden periods (visibility events and samples with
hidden true) are left out of the freeze count and the rate.

sinceVisibleMs is the time from the last hidden-to-visible change to the
freeze: the recorder's own field from schema 4, else the end of the latest
hidden period (visibility events or hidden samples) before the freeze.

Canvas owners: the top 8 creators by MB of the export's canvasSnapshot
(schema 4), else of the last freeze's context.liveCanvasByCreator, are
printed and go to --json as summary.canvasByCreator ([{creator, count, mb}],
null when the export has neither).

Labels, first match wins:
  tab-hidden          the freeze overlaps a hidden period
  after-tab-return    sinceVisibleMs <= AFTER_TAB_RETURN_MS (10000): the
                      first seconds back on the tab, when the browser
                      re-rasterises and re-uploads what it evicted while
                      hidden, whatever else the freeze shows
  first-draw          firstDraws total >= 500000 px (likely GPU upload)
  canvas-churn        canvasesCreated >= 5; an export without firstDraws
                      (recorded before TASK-759) can't show a new canvas's
                      first draw, so there any canvas created counts
  main-thread-script  a long-animation-frame entry's scripts take >= 50% of
                      gapMs, or mainThreadSilenceMs >= 80% of gapMs while the
                      timed layers take < 20%
  gc-suspect          heapDropMB >= 2
  render-or-present   mainThreadSilenceMs < 50% of gapMs, or a long-animation-
                      frame entry's renderStart-to-end >= 50% of gapMs
  game-work           timed layers + physics >= 50% of gapMs
  unknown             none of the above
"""
import argparse
import json
from pathlib import Path
import sys

FIRST_DRAW_PX = 500000
CANVAS_CHURN = 5
GC_DROP_MB = 2
AFTER_TAB_RETURN_MS = 10000
TOP_CREATORS = 8
LABELS = ['tab-hidden', 'after-tab-return', 'first-draw', 'canvas-churn', 'main-thread-script', 'gc-suspect',
          'render-or-present', 'game-work', 'unknown']


def load(path):
    data = Path(path).read_bytes()
    start = data.find(b'{')
    if start < 0:
        raise ValueError(f'{path}: no JSON object found')
    report = json.loads(data[start:].decode('utf-8', errors='replace'))
    if not isinstance(report, dict):
        raise ValueError(f'{path}: not a recorder export')
    return report, start


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def dict_of(value):
    return value if isinstance(value, dict) else {}


def list_of(value):
    return value if isinstance(value, list) else []


def merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def hidden_periods(report, end):
    """Union of [from, to] ms where the page was hidden."""
    intervals, hidden_since = [], None
    events = [e for e in list_of(report.get('visibility'))
              if isinstance(e, dict) and number(e.get('t')) is not None and 'hidden' in e]
    for e in sorted(events, key=lambda e: e['t']):
        if e['hidden'] and hidden_since is None:
            hidden_since = e['t']
        elif not e['hidden'] and hidden_since is not None:
            intervals.append((hidden_since, e['t']))
            hidden_since = None
    if hidden_since is not None:
        intervals.append((hidden_since, max(end or hidden_since, hidden_since)))
    for s in list_of(report.get('samples')):
        if isinstance(s, dict) and s.get('hidden') is True:
            t, gap = number(s.get('t')), number(s.get('gapMs')) or 0
            if t is not None:
                intervals.append((t - gap, t))
    return merge(intervals)


def since_visible(freeze, periods):
    """The recorder's sinceVisibleMs (schema 4), else t minus the end of the
    latest hidden period ending at or before the freeze's start; None if the
    tab was never hidden before it."""
    if 'sinceVisibleMs' in freeze:
        return number(freeze['sinceVisibleMs'])
    t, gap = number(freeze.get('t')), number(freeze.get('gapMs')) or 0
    if t is None:
        return None
    ends = [b for _, b in periods if b <= t - gap]
    return t - max(ends) if ends else None


def canvas_by_creator(report, freezes):
    """Top TOP_CREATORS {creator, count, mb} by mb and where they came from."""
    snapshot = dict_of(report.get('canvasSnapshot'))
    source, creators = 'canvasSnapshot', snapshot.get('liveCanvasByCreator')
    if not isinstance(creators, dict):
        source, creators = 'last freeze', None
        for f in reversed(freezes):
            creators = dict_of(f.get('context')).get('liveCanvasByCreator')
            if isinstance(creators, dict):
                break
    if not isinstance(creators, dict):
        return None, None
    rows = [{'creator': name, 'count': number(dict_of(v).get('count')), 'mb': number(dict_of(v).get('mb')) or 0}
            for name, v in creators.items()]
    rows.sort(key=lambda r: (-r['mb'], r['creator']))
    return rows[:TOP_CREATORS], source


def overlap(a, b, periods):
    return sum(max(0, min(b, q) - max(a, p)) for p, q in periods)


def loaf_facts(loafs):
    """(largest script total in one entry, largest renderStart-to-end, top script)"""
    script_ms, render_ms, top = None, None, None
    for e in list_of(loafs):
        if not isinstance(e, dict):
            continue
        scripts = [s for s in list_of(e.get('scripts')) if isinstance(s, dict)]
        total = sum(number(s.get('duration')) or 0 for s in scripts)
        script_ms = total if script_ms is None else max(script_ms, total)
        start, duration, render = (number(e.get(k)) for k in ('startTime', 'duration', 'renderStart'))
        if start is not None and duration is not None and render:
            ms = start + duration - render
            render_ms = ms if render_ms is None else max(render_ms, ms)
        for s in scripts:
            if top is None or (number(s.get('duration')) or 0) > (number(top.get('duration')) or 0):
                top = s
    return script_ms, render_ms, top


def describe_script(script):
    if not script:
        return None
    url = script.get('sourceURL') or ''
    name = url.rsplit('/', 1)[-1] or script.get('invoker') or '?'
    function = script.get('sourceFunctionName')
    duration = number(script.get('duration'))
    return f'{name}{":" + function if function else ""} {duration:.0f}ms' if duration is not None else name


def label(freeze, hidden, since_visible_ms=None):
    gap = number(freeze.get('gapMs')) or 0
    context = dict_of(freeze.get('context'))
    layers = sum(number(v) or 0 for v in dict_of(freeze.get('layers')).values())
    physics = number(freeze.get('physicsMs')) or 0
    silence = number(freeze.get('mainThreadSilenceMs'))
    heap_drop = number(freeze.get('heapDropMB'))
    canvases = number(context.get('canvasesCreated'))
    script_ms, render_ms, _ = loaf_facts(context.get('loafs'))
    if hidden:
        return 'tab-hidden'
    if since_visible_ms is not None and since_visible_ms <= AFTER_TAB_RETURN_MS:
        return 'after-tab-return'
    if 'firstDraws' in context:
        px = sum((number(d.get('w')) or 0) * (number(d.get('h')) or 0)
                 for d in list_of(context['firstDraws']) if isinstance(d, dict))
        if px >= FIRST_DRAW_PX:
            return 'first-draw'
        if canvases is not None and canvases >= CANVAS_CHURN:
            return 'canvas-churn'
    elif canvases is not None and canvases >= 1:
        return 'canvas-churn'
    if gap > 0:
        if script_ms is not None and script_ms >= 0.5 * gap:
            return 'main-thread-script'
        if silence is not None and silence >= 0.8 * gap and layers < 0.2 * gap:
            return 'main-thread-script'
    if heap_drop is not None and heap_drop >= GC_DROP_MB:
        return 'gc-suspect'
    if gap > 0:
        if silence is not None and silence < 0.5 * gap:
            return 'render-or-present'
        if render_ms is not None and render_ms >= 0.5 * gap:
            return 'render-or-present'
        if layers + physics >= 0.5 * gap:
            return 'game-work'
    return 'unknown'


def analyse(report):
    started, stopped = number(report.get('startedAtMs')), number(report.get('stoppedAtMs'))
    freezes = [f for f in list_of(report.get('freezes')) if isinstance(f, dict)]
    end = stopped
    if end is None:
        times = [number(x.get('t')) for x in freezes + list_of(report.get('samples')) if isinstance(x, dict)]
        times = [t for t in times if t is not None]
        end = max(times) if times else None
    periods = hidden_periods(report, end)
    duration_ms = stopped - started if started is not None and stopped is not None else None
    hidden_ms = overlap(started, stopped, periods) if duration_ms is not None else sum(b - a for a, b in periods)
    rows = []
    for index, f in enumerate(freezes):
        t, gap = number(f.get('t')), number(f.get('gapMs'))
        context = dict_of(f.get('context'))
        hidden = t is not None and overlap(t - (gap or 0), t, periods) > 0
        _, _, top = loaf_facts(context.get('loafs'))
        since = since_visible(f, periods)
        rows.append({
            'index': index,
            't': t, 'gapMs': gap,
            'unaccountedMs': number(f.get('unaccountedMs')),
            'section': context.get('section'),
            'mainThreadSilenceMs': number(f.get('mainThreadSilenceMs')),
            'heapDropMB': number(f.get('heapDropMB')),
            'liveCanvasMB': number(context.get('liveCanvasMB')),
            'sinceVisibleMs': since,
            'topLoafScript': describe_script(top),
            'label': label(f, hidden, since),
        })
    visible = [r for r in rows if r['label'] != 'tab-hidden']
    visible_ms = duration_ms - hidden_ms if duration_ms is not None else None
    counts = {name: sum(r['label'] == name for r in rows) for name in LABELS}
    creators, creators_from = canvas_by_creator(report, freezes)
    summary = {
        'schemaVersion': report.get('schemaVersion'),
        'buildId': report.get('buildId') or None,
        'version': report.get('version'),
        'levelId': report.get('levelId'),
        'durationMs': duration_ms,
        'hiddenMs': hidden_ms,
        'visibleMs': visible_ms,
        'freezes': len(visible),
        'freezesTotal': len(rows),
        'freezesPerMinute': len(visible) / (visible_ms / 60000) if visible_ms else None,
        'labels': {k: v for k, v in counts.items() if v},
        'canvasByCreator': creators,
        'canvasByCreatorFrom': creators_from,
    }
    return summary, rows


def fmt(value, digits=1, unit=''):
    if value is None:
        return 'unknown'
    if isinstance(value, (int, float)):
        return f'{value:.{digits}f}{unit}'
    return str(value)


def render(path, prefix, summary, rows):
    lines = [f'file: {path}']
    if prefix:
        lines.append(f'warning: skipped {prefix} bytes before the first {{ (stray text, not part of the export)')
    schema = summary['schemaVersion']
    if schema not in (1, 2, 3, 4):
        lines.append(f'warning: schemaVersion {schema!r} is not 1-4; reading what is there')
    lines.append(f'schemaVersion: {schema if schema is not None else "unknown"}  version: {fmt(summary["version"])}  level: {fmt(summary["levelId"])}')
    lines.append(f'build: {summary["buildId"] or "unknown"}')
    duration = summary['durationMs']
    lines.append(f'duration: {fmt(duration and duration / 1000, 1, " s")}  hidden: '
                 f'{fmt(summary["hiddenMs"] / 1000, 1, " s")}  visible: '
                 f'{fmt(summary["visibleMs"] and summary["visibleMs"] / 1000, 1, " s")}')
    lines.append(f'freezes: {summary["freezes"]} visible ({summary["freezesTotal"]} total), '
                 f'rate {fmt(summary["freezesPerMinute"], 2, "/min")}')
    lines.append('labels: ' + (', '.join(f'{k} {v}' for k, v in summary['labels'].items()) or 'none'))
    lines.append('')
    lines.append(f'{"t s":>9} {"gapMs":>8} {"unaccMs":>8} {"section":<20} {"silenceMs":>9} '
                 f'{"heapDropMB":>10} {"liveCanvMB":>10} {"sinceVis s":>10}  {"top LoAF script":<28} label')
    for r in rows:
        since = r['sinceVisibleMs']
        lines.append(f'{fmt(r["t"] and r["t"] / 1000, 2):>9} {fmt(r["gapMs"]):>8} {fmt(r["unaccountedMs"]):>8} '
                     f'{fmt(r["section"]):<20} {fmt(r["mainThreadSilenceMs"]):>9} {fmt(r["heapDropMB"]):>10} '
                     f'{fmt(r["liveCanvasMB"]):>10} {fmt(since and since / 1000, 2):>10}  '
                     f'{fmt(r["topLoafScript"]):<28} {r["label"]}')
    lines.append('')
    creators = summary['canvasByCreator']
    if creators is None:
        lines.append('live canvases by creator: unknown (export has no liveCanvasByCreator)')
    else:
        lines.append(f'live canvases by creator (top {TOP_CREATORS} by MB, from {summary["canvasByCreatorFrom"]}):')
        for c in creators:
            lines.append(f'{fmt(c["mb"], 1):>9} MB {fmt(c["count"], 0):>5}  {c["creator"]}')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Label the freezes in a ?visualsPerf=1 export')
    parser.add_argument('recording')
    parser.add_argument('--json', dest='json_out', help='also write {summary, rows} here')
    args = parser.parse_args(argv)
    try:
        report, prefix = load(args.recording)
    except (OSError, ValueError) as e:
        print(f'freeze_report: {e}', file=sys.stderr)
        return 1
    summary, rows = analyse(report)
    print(render(args.recording, prefix, summary, rows))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({'file': args.recording, 'summary': summary, 'rows': rows},
                                                  indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
