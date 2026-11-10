"""An SVG as a PNG with no browser (thorough conversion Task 3): the map check's picture, which a trace agent compares
with the scan. resvg (`resvg-py`, a wheel with no system libraries) draws it; the WGR1 QA took a screenshot in
Chromium instead, which a host install may not have.
"""

from __future__ import annotations

from pathlib import Path

import resvg_py

WIDTH = 1200


def svg_to_png(svg: str, out: Path, width: int = WIDTH) -> None:
    """`svg` drawn `width` pixels wide on white, its height to scale, written to `out`. `ValueError` for an SVG resvg
    can't draw."""
    out.write_bytes(bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width, background="#ffffff")))
