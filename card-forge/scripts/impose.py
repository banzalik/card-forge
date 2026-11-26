#!/usr/bin/env python3
"""Deterministic CR80 duplex print imposition coordinate generator.

Prints JSON describing where every card slot sits on the front (odd) and
back (even) page of a duplex sheet, in millimetres from the top-left corner
of the paper.  Stdlib only, so it can run anywhere Python 3.9+ exists.

    python3 scripts/impose.py --paper letter --per-page 8 --flip long-edge
"""
from __future__ import annotations

import argparse
import json
import sys

PAPER_SIZES = {
    "letter": (215.9, 279.4),
    "a4": (210.0, 297.0),
}

# perPage -> (cols, rows, {paper: (gutter_x, gutter_y)})
GRID_PRESETS = {
    1: (1, 1, {"letter": (0.0, 0.0), "a4": (0.0, 0.0)}),
    2: (1, 2, {"letter": (0.0, 12.0), "a4": (0.0, 15.0)}),
    4: (2, 2, {"letter": (10.0, 12.0), "a4": (8.0, 15.0)}),
    8: (2, 4, {"letter": (10.0, 8.0), "a4": (8.0, 10.0)}),
    10: (2, 5, {"letter": (10.0, 2.0), "a4": (8.0, 4.0)}),
}

CR80_W = 85.60
CR80_H = 53.98
CR80_RADIUS = 3.18
DEFAULT_BLEED = 2.0
# Most desktop laser/inkjet printers cannot print closer than ~1/4" to the edge.
SAFE_PRINTER_MARGIN = 6.35
FLIPS = ("long-edge", "short-edge")


def compute_imposition(
    paper: str,
    per_page: int,
    flip: str,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    bleed: float = DEFAULT_BLEED,
) -> dict:
    if paper not in PAPER_SIZES:
        raise ValueError(f"Unsupported paper: {paper}. Choose from {list(PAPER_SIZES)}")
    if per_page not in GRID_PRESETS:
        raise ValueError(f"Unsupported per_page: {per_page}. Choose from {list(GRID_PRESETS)}")
    if flip not in FLIPS:
        raise ValueError(f"Unsupported flip: {flip}. Choose from {list(FLIPS)}")
    if bleed < 0:
        raise ValueError("bleed must be >= 0")

    pw, ph = PAPER_SIZES[paper]
    cols, rows, gutters = GRID_PRESETS[per_page]
    gx, gy = gutters[paper]

    grid_w = cols * CR80_W + (cols - 1) * gx
    grid_h = rows * CR80_H + (rows - 1) * gy
    x0 = (pw - grid_w) / 2.0
    y0 = (ph - grid_h) / 2.0

    # Adjacent cards may not share bleed: clip bleed at the middle of the gutter.
    # The outer edge keeps the full bleed (limited only by the paper edge).
    eff_bleed_x = min(bleed, gx / 2.0) if cols > 1 else bleed
    eff_bleed_y = min(bleed, gy / 2.0) if rows > 1 else bleed
    outer_bleed_x = max(0.0, min(bleed, x0))
    outer_bleed_y = max(0.0, min(bleed, y0))

    warnings: list[str] = []
    if bleed > 0 and cols > 1 and gx < 2 * bleed:
        warnings.append(
            f"Horizontal gutter {gx}mm < 2 x bleed ({2 * bleed}mm): bleed clipped to {eff_bleed_x}mm between columns."
        )
    if bleed > 0 and rows > 1 and gy < 2 * bleed:
        warnings.append(
            f"Vertical gutter {gy}mm < 2 x bleed ({2 * bleed}mm): bleed clipped to {eff_bleed_y}mm between rows."
        )
    margin = min(x0, y0)
    if margin < SAFE_PRINTER_MARGIN:
        warnings.append(
            f"Outer margin is only {round(margin, 3)}mm (< {SAFE_PRINTER_MARGIN}mm). "
            "Most desktop printers will clip the outermost cards; use borderless printing or fewer cards per page."
        )
    if margin - bleed < 3.0 and bleed > 0:
        warnings.append("Not enough outer margin to draw 3mm crop marks outside the bleed; crop marks will be shortened or omitted.")

    pitch_x = CR80_W + gx
    pitch_y = CR80_H + gy
    slots = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            fx = round(x0 + c * pitch_x, 3)
            fy = round(y0 + r * pitch_y, 3)

            if flip == "long-edge":
                bc, br = (cols - 1) - c, r
            else:
                bc, br = c, (rows - 1) - r

            bx = round(x0 + bc * pitch_x + offset_x, 3)
            by = round(y0 + br * pitch_y + offset_y, 3)

            slots.append({
                "slotIndex": idx,
                "front": {"col": c, "row": r, "x_mm": fx, "y_mm": fy},
                "back": {"col": bc, "row": br, "x_mm": bx, "y_mm": by},
            })
            idx += 1

    return {
        "paper": {"name": paper, "width_mm": pw, "height_mm": ph},
        "card": {
            "width_mm": CR80_W,
            "height_mm": CR80_H,
            "radius_mm": CR80_RADIUS,
            "bleed_mm": bleed,
            # Bleed actually available: "inner" between neighbouring cards, "outer" toward the paper edge.
            "effectiveBleed_mm": {
                "inner": {"x": round(eff_bleed_x, 3), "y": round(eff_bleed_y, 3)},
                "outer": {"x": round(outer_bleed_x, 3), "y": round(outer_bleed_y, 3)},
            },
        },
        "grid": {
            "cols": cols,
            "rows": rows,
            "perPage": per_page,
            "gutter_mm": {"x": gx, "y": gy},
            "origin_mm": {"x": round(x0, 3), "y": round(y0, 3)},
            "duplexFlip": flip,
        },
        "calibration_mm": {"offsetX": offset_x, "offsetY": offset_y},
        "slots": slots,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paper", default="letter", choices=sorted(PAPER_SIZES))
    parser.add_argument("--per-page", type=int, default=8, choices=sorted(GRID_PRESETS))
    parser.add_argument("--flip", default="long-edge", choices=FLIPS)
    parser.add_argument("--offset-x", type=float, default=0.0, help="Back-page X calibration (mm, + moves right)")
    parser.add_argument("--offset-y", type=float, default=0.0, help="Back-page Y calibration (mm, + moves down)")
    parser.add_argument("--bleed", type=float, default=DEFAULT_BLEED, help="Bleed in mm (0 to disable)")
    args = parser.parse_args(argv)
    result = compute_imposition(args.paper, args.per_page, args.flip, args.offset_x, args.offset_y, args.bleed)
    print(json.dumps(result, indent=2))
    for w in result["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
