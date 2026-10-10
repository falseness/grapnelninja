"""Test a nonzero-winding exclusion clip against the current even-odd clip.

Reverse only the circular subpath, so its winding cancels the outer rectangle.
Keep geometry bounds, sampling, textures, blending and alpha unchanged. The
shared harness rejects any exact identity mismatch before paired live timing.
This tool edits only an extracted candidate beneath the evidence directory.
"""
import argparse
from pathlib import Path

from profile_y8_glow_pattern import capture


def transform(source):
    old = """player.getRingOuterRadius() * exclusionRadiusRatio, 0, Math.PI * 2)
            this.ctx.clip('evenodd')"""
    new = """player.getRingOuterRadius() * exclusionRadiusRatio, 0, -Math.PI * 2, true)
            this.ctx.clip('nonzero')"""
    assert source.count(old) == 1
    return source.replace(old, new)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    capture(args.out.resolve(), transform=transform,
            hypothesis='Opposite-winding circular exclusion with nonzero clip; unchanged geometry bounds',
            driver=Path(__file__).resolve())
