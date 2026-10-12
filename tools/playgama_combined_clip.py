"""Freeze committed runtime and generate the isolated TASK-324 support clips.

No performance/adoption claim. Existing output directories are never overwritten.
"""
import argparse
import difflib
import json
from pathlib import Path
from build_playgama import runtime, sha
from playgama_ambient_clip import METHODS
from playgama_light_clip import SUPPORT, CLIP


def replace_once(text, old, new):
    assert text.count(old) == 1, repr(old)
    return text.replace(old, new)


def candidate(original):
    text = original.decode()
    # Explicitly authorize only the known mote callback. Unknown drawScreen
    # callers still render, but take the original complete composite.
    text = replace_once(text, 'this.drawAmbientMotes(view))', 'this.drawAmbientMotes(view), true)')
    methods = METHODS.replace('        super.renderGlow(a, b, c, d, e, f, drawShapes, arg)', '''        this.support = null
        super.renderGlow(a, b, c, d, e, f, drawShapes, arg)
        if (!this.supportedMotes) return''')
    methods = methods.replace('        const first = this.levels[0].canvas', '''        if (!layout || layout.length % 4 || !Array.from(layout).every(Number.isFinite)
            || ![a,b,c,d,e,f].every(Number.isFinite)) return
        const first = this.levels[0].canvas''')
    methods = methods.replace('        const config = this.getConfig()\n        this.ctx.save()', '''        const config = this.getConfig()
        // Opaque black is neutral only for the original additive composite.
        if (config.compositeOperation !== 'lighter') return super.composite(player)
        this.ctx.save()''')
    methods = '''
    resize()
    {
        this.support = null
        super.resize()
    }
    drawScreen(drawShapes, supportedMotes = false)
    {
        this.support = null
        this.supportedMotes = supportedMotes
        try { super.drawScreen(drawShapes) }
        finally { this.supportedMotes = false; this.support = null }
    }
''' + methods
    text = replace_once(text, 'class AmbientGlowRenderer extends BloomRenderer\n{',
                        'class AmbientGlowRenderer extends BloomRenderer\n{\n' + methods)
    start = text.index('class LightmapRenderer')
    end = text.index('\nfunction positiveModulo', start)
    light = text[start:end]
    light = light.replace('        this.hasLights = false\n',
                          '        this.hasLights = false\n        this.clipSupport = []\n        this.clipFallback = false\n')
    light = replace_once(light, '    resize()\n    {', '''    resize()
    {
        this.clipSupport = []
        this.clipFallback = true''')
    light = replace_once(light, '    clear()\n    {', '''    clear()
    {
        this.clipSupport = []
        this.clipFallback = true''')
    light = replace_once(light, '    drawRadialLight(x, y, radius, color, alpha)\n    {', '''    drawRadialLight(x, y, radius, color, alpha)
    {
        // Radial support is deliberately unsupported: retain full composition.
        this.clipFallback = true''')
    light = replace_once(light, '            return\n        const box = getElementCullBox(element)',
                        '''        {
            // Existing boundary surfaces are known non-emitters.
            if (!(element instanceof Ground) && !(element instanceof Side))
                this.clipFallback = true
            return
        }
        const box = getElementCullBox(element)''')
    support = SUPPORT + '''        if (![sx, sy, sprite.width, sprite.height, toLight].every(Number.isFinite)
            || toLight <= 0) this.clipFallback = true
'''
    light = replace_once(light, '        this.lightCtx.drawImage(sprite, x - spread, y - spread,\n',
                        support + '        this.lightCtx.drawImage(sprite, x - spread, y - spread,\n')
    guarded = '''        // Replaced emitter entry points have no proven support envelope.
        if (!this.clipFallback && this.clipSupport.length &&
            this.draw === LightmapRenderer.prototype.draw &&
            this.drawWorldLights === LightmapRenderer.prototype.drawWorldLights &&
            this.drawElementLight === LightmapRenderer.prototype.drawElementLight &&
            this.drawRadialLight === LightmapRenderer.prototype.drawRadialLight) {
''' + CLIP + '        }\n'
    light = replace_once(light, '        this.ctx.drawImage(this.lightCanvas, 0, 0, viewWidth, viewHeight)',
                        guarded + '        this.ctx.drawImage(this.lightCanvas, 0, 0, viewWidth, viewHeight)')
    return (text[:start] + light + text[end:]).encode()


def prepare(revision, out):
    revision, files = runtime(revision, revision)
    out.mkdir(parents=True, exist_ok=False)
    for arm in ('control', 'candidate'):
        members = dict(files)
        if arm == 'candidate': members['render/effects.js'] = candidate(files['render/effects.js'])
        for name, data in members.items():
            path = out / arm / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o444)
        source = {'revision': revision, 'arm': arm, 'members': {p: sha(b) for p,b in sorted(members.items())}}
        (out/arm/'source.json').write_text(json.dumps(source, indent=2)+'\n')
        (out/arm/'source.json').chmod(0o444)
        print(f'PASS {arm} immutable runtime members={len(members)} revision={revision}')
    diff = ''.join(difflib.unified_diff(files['render/effects.js'].decode().splitlines(True),
                  candidate(files['render/effects.js']).decode().splitlines(True),
                  fromfile='control/render/effects.js', tofile='candidate/render/effects.js'))
    (out/'candidate.diff').write_text(diff)
    print('PASS combined all-four-level ambient and world-light candidate; no FPS claim')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    prepare(args.revision, args.out)
