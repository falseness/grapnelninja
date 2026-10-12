"""Offline exact-disjoint-rectangle screen for saved ambient support layouts.

This does not modify a runtime or assert browser performance. Stop before a
browser experiment when the proposed rectangle path does not reduce complexity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
import shutil


JS_UNION = r'''function ambientDisjointUnion(rectangles) {
    const xs = [...new Set(rectangles.flatMap(r => [r[0], r[2]]))].sort((a,b)=>a-b)
    const result = []
    let previous = new Map()
    for (let i = 1; i < xs.length; ++i) {
        const left = xs[i-1], right = xs[i], spans = []
        const intervals = rectangles.filter(r => r[0] < right && r[2] > left && r[3] > r[1])
            .map(r => [r[1],r[3]]).sort((a,b)=>a[0]-b[0] || a[1]-b[1])
        for (const [top,bottom] of intervals) {
            const last = spans[spans.length-1]
            if (last && top <= last[1]) last[1] = Math.max(last[1],bottom)
            else spans.push([top,bottom])
        }
        const current = new Map()
        for (const [top,bottom] of spans) {
            const key = top+','+bottom
            let index = previous.get(key)
            if (index === undefined) {
                index = result.length
                result.push([left,top,right,bottom])
            } else result[index][2] = right
            current.set(key,index)
        }
        previous = current
    }
    return result
}
'''


def prepare(source, out):
    """A must already be the all-level clipped snapshot; change only its path."""
    assert not out.exists(), 'preserve previous experiments'
    shutil.copytree(source, out)
    path = out/'render/effects.js'
    original = path.read_text()
    marker = 'for (const [x,y,r,b] of this.support[i]) this.ctx.rect(x,y,r-x,b-y)'
    assert original.count(marker) == 1
    assert 'if (i < this.levels.length - 1)' not in original
    path.chmod(0o644)
    path.write_text(JS_UNION+'\n'+original.replace(marker,
        'for (const [x,y,r,b] of ambientDisjointUnion(this.support[i])) this.ctx.rect(x,y,r-x,b-y)'))


def disjoint_union(rectangles):
    """Sweep x slabs, merge y intervals, then join identical adjacent spans."""
    xs = sorted({r[i] for r in rectangles for i in (0, 2)})
    result = []
    previous = {}
    for left, right in zip(xs, xs[1:]):
        spans = []
        for top, bottom in sorted((y, b) for x, y, r, b in rectangles
                                  if x < right and r > left and b > y):
            if spans and top <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], bottom)
            else:
                spans.append([top, bottom])
        current = {}
        for top, bottom in spans:
            key = (top, bottom)
            index = previous.get(key)
            if index is None:
                index = len(result)
                result.append([left, top, right, bottom])
            else:
                result[index][2] = right
            current[key] = index
        previous = current
    return result


def pixel_rows(rectangles, width, height):
    """Independent integer-pixel oracle, using one bit per covered pixel."""
    rows = [0] * height
    area = 0
    for x, y, right, bottom in rectangles:
        assert all(isinstance(v, int) for v in (x, y, right, bottom))
        assert 0 <= x <= right <= width and 0 <= y <= bottom <= height
        bits = ((1 << (right - x)) - 1) << x
        area += (right - x) * (bottom - y)
        for row in range(y, bottom):
            rows[row] |= bits
    return rows, area


def screen(layouts):
    records = []
    for path in sorted(layouts.glob('*support.json')):
        data = json.loads(path.read_text())
        width, height = data['backing']
        for level, rectangles in enumerate(data['support']):
            candidate = disjoint_union(rectangles)
            original_rows, _ = pixel_rows(rectangles, width, height)
            union_rows, area = pixel_rows(candidate, width, height)
            assert original_rows == union_rows, (path, level, 'coverage differs')
            assert area == sum(bin(row).count('1') for row in union_rows), 'overlap'
            timings = []
            for _ in range(100):
                started = time.perf_counter_ns()
                disjoint_union(rectangles)
                timings.append((time.perf_counter_ns() - started) / 1e6)
            records.append(dict(layout=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                level=level, backing=[width, height], equal_pixels=True,
                                disjoint=True, covered_pixels=area,
                                a_rectangles=len(rectangles), b_rectangles=len(candidate),
                                a_edges=4*len(rectangles), b_edges=4*len(candidate),
                                offline_python_union_median_ms=statistics.median(timings),
                                candidate_rectangles=candidate))
    assert records, 'no saved support layouts'
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layouts', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert not args.out.exists(), 'preserve previous results'
    records = screen(args.layouts)
    a = sum(r['a_edges'] for r in records)
    b = sum(r['b_edges'] for r in records)
    result = dict(records=records, a_edges=a, b_edges=b,
                  coverage='PASS', complexity='PASS' if b < a else 'FAIL',
                  cost_scope='Offline Python only; not browser JS or frame savings')
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'PASS exact integer coverage and disjointness: {len(records)} layouts/levels')
    for level in range(4):
        rows = [r for r in records if r['level'] == level]
        print(f'LEVEL {level} rectangles A={sum(r["a_rectangles"] for r in rows)} '
              f'B={sum(r["b_rectangles"] for r in rows)}')
    print(f'{result["complexity"]} path complexity: A={a} edges B={b} edges')
    print('COST offline Python median ms range',
          min(r['offline_python_union_median_ms'] for r in records),
          max(r['offline_python_union_median_ms'] for r in records))
