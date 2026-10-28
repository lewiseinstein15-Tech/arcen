"""Rasterize the captured SVG frames to PNG with CairoSVG.

CairoSVG honors the Fira Code @font-face metrics baked into the SVG export;
ImageMagick's default SVG delegate substitutes fonts and mis-positions
adjacent style runs, producing visible gaps.
"""
import pathlib

import cairosvg

SHOTS = pathlib.Path(__file__).parent / "shots"

for svg in sorted(SHOTS.glob("*.svg")):
    cairosvg.svg2png(
        url=str(svg),
        write_to=str(svg.with_suffix(".png")),
        background_color="#0B0E14",
        output_width=1856,
    )
    print("png:", svg.with_suffix(".png").name)
