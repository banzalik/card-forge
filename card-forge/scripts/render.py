#!/usr/bin/env python3
"""Render CR80 cards to a duplex-imposed print sheet (HTML, and PDF if a renderer exists).

Examples:
    python3 scripts/render.py assets/samples/auto-insurance.json --per-page 8 --mode copies --out dist/
    python3 scripts/render.py cards.csv --template generic-id --per-page 10 --paper a4 --out dist/
    python3 scripts/render.py --calibrate --paper letter --flip long-edge --out dist/

Page order: odd pages are fronts, even pages are the matching backs, so a
duplex printer prints each front/back pair on one physical sheet.
PDF output uses WeasyPrint if installed, otherwise Chromium via Playwright (Node).
"""
from __future__ import annotations

import argparse
import base64
import mimetypes
import shutil
import subprocess
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from barcodes import barcode_svg  # noqa: E402
from cardforge_common import TEMPLATES, CardError, load_records, normalize, safe_id  # noqa: E402
from impose import CR80_H, CR80_W, DEFAULT_BLEED, FLIPS, GRID_PRESETS, PAPER_SIZES, compute_imposition  # noqa: E402

HOLDER_LABEL = {
    "auto-insurance": "Named Insured",
    "medical-doctor": "Member / Patient",
    "membership-loyalty": "Member",
    "generic-id": "Name",
}
ID_LABEL = {
    "auto-insurance": "Policy Number",
    "medical-doctor": "Member ID",
    "membership-loyalty": "Member ID",
    "generic-id": "ID Number",
}

CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "card.css"


# --------------------------------------------------------------------------- helpers
def _data_uri(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        print(f"warning: image not found: {p}", file=sys.stderr)
        return None
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def _fmt_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        y, m, d = value.split("-")
        return f"{m}/{d}/{y}"
    except ValueError:
        return value


def _kv(label: str, value: str) -> str:
    return f'<div><div class="lbl">{escape(label)}</div><div class="val">{escape(value)}</div></div>'


def _bleeds(col: int, row: int, cols: int, rows: int, eff: dict) -> tuple[float, float, float, float]:
    inner, outer = eff["inner"], eff["outer"]
    left = outer["x"] if col == 0 else inner["x"]
    right = outer["x"] if col == cols - 1 else inner["x"]
    top = outer["y"] if row == 0 else inner["y"]
    bottom = outer["y"] if row == rows - 1 else inner["y"]
    return left, top, right, bottom


def _slot(x: float, y: float, bleeds, inner_html: str, guides: bool) -> str:
    bl, bt, br, bb = bleeds
    w, h = CR80_W + bl + br, CR80_H + bt + bb
    guide = (
        f'<div class="guide" style="left:{x:.3f}mm;top:{y:.3f}mm"></div>' if guides else ""
    )
    style = f"left:{x - bl:.3f}mm;top:{y - bt:.3f}mm;width:{w:.3f}mm;height:{h:.3f}mm;--bl:{bl}mm;--bt:{bt}mm;--br:{br}mm;--bb:{bb}mm"
    return f'<div class="bleedbox" style="{style}">{inner_html}</div>{guide}'


# --------------------------------------------------------------------------- card faces
def front_html(card: dict, bleeds) -> str:
    bl, bt, br, bb = bleeds
    b, f, tpl = card["branding"], card["front"], card["template"]
    logo = _data_uri(b.get("logoPath"))
    photo = _data_uri(b.get("photoPath"))
    badge = TEMPLATES[tpl]["badge"]
    if tpl == "membership-loyalty":
        tier = next((x["value"] for x in f.get("fields", []) if x.get("key") == "tier"), None)
        badge = (tier or badge).upper()

    items = [(x["label"], x["value"]) for x in f.get("fields", []) if not (tpl == "membership-loyalty" and x.get("key") == "tier")]
    eff, exp = _fmt_date(f.get("effectiveDate")), _fmt_date(f.get("expirationDate"))
    if tpl == "membership-loyalty":
        if eff:
            items.append(("Member Since", eff))
    elif eff:
        items.append(("Effective", eff))
    if exp:
        items.append(("Expires", exp))
    cols = 2 if len(items) <= 4 or photo else 3

    head = (
        (f'<img class="logo" src="{logo}" alt="">' if logo else "")
        + f'<div class="f-issuer"><div class="name">{escape(f["issuerName"])}</div>'
        + (f'<div class="sub">{escape(f["subtitle"])}</div>' if f.get("subtitle") else "")
        + "</div>"
        + f'<div class="badge" style="background:{b["accentColor"]};color:{b["textColor"]}">{escape(badge)}</div>'
    )
    main = (
        f'<div class="f-holder">{_kv(HOLDER_LABEL[tpl], f["holderName"])}</div>'
        f'<div class="f-id"><div class="lbl">{ID_LABEL[tpl]}</div><div class="val mono">{escape(f["idNumber"])}</div></div>'
        f'<div class="f-grid" style="--cols:{cols}">{"".join(_kv(k, v) for k, v in items)}</div>'
    )
    return (
        f'<div class="f-band" style="height:calc({bt}mm + 13.4mm);background:{b["primaryColor"]}"></div>'
        f'<div class="f-stripe" style="height:calc({bb}mm + 2.2mm);background:{b["accentColor"]}"></div>'
        f'<div class="trim" style="left:{bl}mm;top:{bt}mm">'
        f'<div class="f-head" style="color:{b["textColor"]}">{head}</div>'
        f'<div class="f-body"><div class="f-main">{main}</div>'
        + (f'<img class="f-photo" src="{photo}" alt="">' if photo else "")
        + "</div></div>"
    )


def back_html(card: dict, bleeds) -> str:
    bl, bt, br, bb = bleeds
    back = card["back"]
    mag = bool(back.get("showMagStripe"))
    # ISO/IEC 7811: stripe from 5.54mm to ~15.82mm below the top edge (back side).
    mag_html = f'<div class="b-mag" style="top:calc({bt}mm + 5.54mm);height:10.28mm"></div>' if mag else ""
    content_top = 18.0 if mag else 3.0

    rows = [*(back.get("contacts") or []), *(back.get("fields") or [])]
    text = ""
    if back.get("header"):
        text += f'<div class="b-head">{escape(back["header"])}</div>'
    text += "".join(
        f'<div class="b-row"><span class="k">{escape(r["label"])}</span><span class="v">{escape(r["value"])}</span></div>' for r in rows
    )
    if back.get("showSignatureStrip"):
        text += '<div class="b-sig"><span>AUTHORIZED SIGNATURE</span></div>'
    if back.get("legalNotice"):
        text += f'<div class="b-legal">{escape(back["legalNotice"])}</div>'

    bc = back.get("barcode")
    bc_html = ""
    if bc:
        alt = f'<div class="alt mono">{escape(bc.get("altText") or "")}</div>' if bc.get("altText") else ""
        cls = "bc-QR" if bc["format"] == "QR" else "bc-wide"
        bc_html = f'<div class="bc {cls}"><div class="code">{barcode_svg(bc["format"], bc["value"])}</div>{alt}</div>'

    if bc and bc["format"] == "QR":
        body = f'<div class="b-text">{text}</div>{bc_html}'
        direction = "row"
    else:
        body = f'<div class="b-text">{text}</div>{bc_html}'
        direction = "column"
    return (
        mag_html
        + f'<div class="trim" style="left:{bl}mm;top:{bt}mm">'
        + f'<div class="b-content" style="top:{content_top}mm;flex-direction:{direction}">{body}</div></div>'
    )


# --------------------------------------------------------------------------- sheets
def _crop_marks(imp: dict, which: str) -> str:
    """Hair-line crop marks on the sheet perimeter, aligned to every trim line, kept outside the bleed."""
    pw, ph = imp["paper"]["width_mm"], imp["paper"]["height_mm"]
    eff = imp["card"]["effectiveBleed_mm"]["outer"]
    gap = 1.0
    xs, ys = set(), set()
    for s in imp["slots"]:
        pos = s[which]
        xs.update((pos["x_mm"], pos["x_mm"] + CR80_W))
        ys.update((pos["y_mm"], pos["y_mm"] + CR80_H))
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    lw = 0.1
    out = []
    for x in sorted(xs):
        for y0, y1 in ((max(0, min_y - eff["y"] - gap - 3.0), min_y - eff["y"] - gap), (max_y + eff["y"] + gap, min(ph, max_y + eff["y"] + gap + 3.0))):
            if y1 - y0 >= 1.0:
                out.append(f'<div class="crop" style="left:{x - lw / 2:.3f}mm;top:{y0:.3f}mm;width:{lw}mm;height:{y1 - y0:.3f}mm"></div>')
    for y in sorted(ys):
        for x0, x1 in ((max(0, min_x - eff["x"] - gap - 3.0), min_x - eff["x"] - gap), (max_x + eff["x"] + gap, min(pw, max_x + eff["x"] + gap + 3.0))):
            if x1 - x0 >= 1.0:
                out.append(f'<div class="crop" style="left:{x0:.3f}mm;top:{y - lw / 2:.3f}mm;width:{x1 - x0:.3f}mm;height:{lw}mm"></div>')
    return "".join(out)


def _doc(imp: dict, sheets: list[str], title: str) -> str:
    pw, ph = imp["paper"]["width_mm"], imp["paper"]["height_mm"]
    css = f"@page {{ size: {pw}mm {ph}mm; margin: 0; }}\n:root {{ --pw: {pw}mm; --ph: {ph}mm; }}\n" + CSS_PATH.read_text(encoding="utf-8")
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>'
        f"<style>{css}</style></head><body>{''.join(sheets)}</body></html>"
    )


def build_sheets(cards: list[dict], imp: dict, mode: str, crop_marks: bool, guides: bool) -> str:
    per_page = imp["grid"]["perPage"]
    cols, rows = imp["grid"]["cols"], imp["grid"]["rows"]
    eff = imp["card"]["effectiveBleed_mm"]
    if mode == "copies":
        if len(cards) != 1:
            print(f"note: --mode copies uses the first of {len(cards)} cards", file=sys.stderr)
        pages = [[cards[0]] * per_page]
    else:
        pages = [cards[i:i + per_page] for i in range(0, len(cards), per_page)]

    sheets = []
    for batch in pages:
        fronts, backs = [], []
        for slot, card in zip(imp["slots"], batch):
            fpos, bpos = slot["front"], slot["back"]
            fb = _bleeds(fpos["col"], fpos["row"], cols, rows, eff)
            bb = _bleeds(bpos["col"], bpos["row"], cols, rows, eff)
            fronts.append(_slot(fpos["x_mm"], fpos["y_mm"], fb, front_html(card, fb), guides))
            backs.append(_slot(bpos["x_mm"], bpos["y_mm"], bb, back_html(card, bb), guides))
        fcrop = _crop_marks(imp, "front") if crop_marks else ""
        bcrop = _crop_marks(imp, "back") if crop_marks else ""
        sheets.append(f'<section class="sheet front">{"".join(fronts)}{fcrop}</section>')
        sheets.append(f'<section class="sheet back">{"".join(backs)}{bcrop}</section>')
    return _doc(imp, sheets, "CardForge print sheet")


def build_calibration(imp: dict) -> str:
    """Two-page target: crosshairs at every card centre plus mm rulers on both sides.

    Print duplex, hold to a light, and measure how far the back crosshairs sit from
    the front ones (as seen from the FRONT).  Back drift seen from the front reads
    mirrored on the axis you flipped across, so:
      long-edge:  offsetX = -(dx seen from front), offsetY = dy seen from front
      short-edge: offsetX = dx seen from front,    offsetY = -(dy seen from front)
    """
    pw, ph = imp["paper"]["width_mm"], imp["paper"]["height_mm"]
    flip = imp["grid"]["duplexFlip"]

    def page(which: str, label: str) -> str:
        parts = []
        for s in imp["slots"]:
            p = s[which]
            cx, cy = p["x_mm"] + CR80_W / 2, p["y_mm"] + CR80_H / 2
            parts.append(f'<div class="cal-cross" style="left:{cx:.3f}mm;top:{cy:.3f}mm"></div>')
            parts.append(f'<div class="guide" style="left:{p["x_mm"]:.3f}mm;top:{p["y_mm"]:.3f}mm;border-color:#999"></div>')
        # rulers through page centre (ticks every 1mm, longer every 5mm, labelled every 10mm)
        mx, my = pw / 2, ph / 2
        for i in range(-30, 31):
            ln = 3.0 if i % 10 == 0 else (2.0 if i % 5 == 0 else 1.0)
            parts.append(f'<div class="tick" style="left:{mx + i:.3f}mm;top:{my - ln:.3f}mm;width:0.1mm;height:{ln}mm"></div>')
            parts.append(f'<div class="tick" style="left:{mx - ln:.3f}mm;top:{my + i:.3f}mm;height:0.1mm;width:{ln}mm"></div>')
            if i % 10 == 0 and i:
                parts.append(f'<div class="ruler" style="left:{mx + i - 1:.3f}mm;top:{my - 5.5:.3f}mm">{i}</div>')
                parts.append(f'<div class="ruler" style="left:{mx - 7:.3f}mm;top:{my + i - 0.8:.3f}mm">{i}</div>')
        note = (
            f"<b>CardForge duplex calibration — {label}</b><br>"
            f"Paper {imp['paper']['name']} · {imp['grid']['perPage']} per page · flip {flip} · "
            f"current offset X {imp['calibration_mm']['offsetX']}mm, Y {imp['calibration_mm']['offsetY']}mm"
        )
        if which == "front":
            note += (
                "<br>Print BOTH pages duplex (actual size / 100%, no fit-to-page), "
                + ("flip on long edge" if flip == "long-edge" else "flip on short edge")
                + ". Hold the sheet to a light and read where the back crosshair sits relative to the front one, "
                "using the rulers. "
                + ("Use offsetX = −dx, offsetY = +dy." if flip == "long-edge" else "Use offsetX = +dx, offsetY = −dy.")
                + " (dx: + is right, dy: + is down, both as seen from this side.)"
            )
        parts.append(f'<div class="cal-note" style="top:3mm">{note}</div>')
        return f'<section class="sheet {which}">{"".join(parts)}</section>'

    return _doc(imp, [page("front", "page 1 (front)"), page("back", "page 2 (back)")], "CardForge calibration")


# --------------------------------------------------------------------------- PDF
def html_to_pdf(html_path: Path, pdf_path: Path) -> str | None:
    """Return the engine used, or None when no PDF renderer is available."""
    try:
        from weasyprint import HTML  # type: ignore

        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
        return "weasyprint"
    except ImportError:
        pass
    node = shutil.which("node")
    helper = Path(__file__).resolve().parent / "html2pdf.mjs"
    if node and helper.exists():
        proc = subprocess.run([node, str(helper), str(html_path), str(pdf_path)], capture_output=True, text=True)
        if proc.returncode == 0:
            return "chromium"
        print(proc.stderr.strip(), file=sys.stderr)
    return None


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render CR80 cards to a duplex print sheet.")
    ap.add_argument("input", nargs="?", help="Card JSON (object or array) or CSV with dotted headers")
    ap.add_argument("--template", choices=sorted(TEMPLATES), help="Override the template of every record")
    ap.add_argument("--paper", default="letter", choices=sorted(PAPER_SIZES))
    ap.add_argument("--per-page", type=int, default=8, choices=sorted(GRID_PRESETS))
    ap.add_argument("--mode", default="batch", choices=["batch", "copies"])
    ap.add_argument("--flip", default="long-edge", choices=FLIPS)
    ap.add_argument("--offset-x", type=float, default=0.0)
    ap.add_argument("--offset-y", type=float, default=0.0)
    ap.add_argument("--bleed", action=argparse.BooleanOptionalAction, default=True, help="2mm bleed (default on)")
    ap.add_argument("--crop-marks", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--guides", action="store_true", help="Draw dashed rounded trim outlines (proofing only)")
    ap.add_argument("--calibrate", action="store_true", help="Emit a duplex calibration target instead of cards")
    ap.add_argument("--html-only", action="store_true", help="Skip PDF conversion")
    ap.add_argument("--out", default="dist", help="Output directory")
    ap.add_argument("--name", help="Output base filename (default derived from input)")
    a = ap.parse_args(argv)

    imp = compute_imposition(a.paper, a.per_page, a.flip, a.offset_x, a.offset_y, DEFAULT_BLEED if a.bleed else 0.0)
    for w in imp["warnings"]:
        print(f"warning: {w}", file=sys.stderr)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.calibrate:
        html = build_calibration(imp)
        base = a.name or f"calibration-{a.paper}-{a.flip}"
    else:
        if not a.input:
            ap.error("input is required unless --calibrate is given")
        src = Path(a.input)
        try:
            cards = [normalize(r, a.template, src.parent) for r in load_records(src)]
        except CardError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if not cards:
            print("error: no cards found in input", file=sys.stderr)
            return 2
        html = build_sheets(cards, imp, a.mode, a.crop_marks, a.guides)
        base = a.name or f"{safe_id(src.stem)}-{a.paper}-{a.per_page}up"

    html_path = out / f"{base}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"html: {html_path}")
    if not a.html_only:
        pdf_path = out / f"{base}.pdf"
        engine = html_to_pdf(html_path, pdf_path)
        if engine:
            print(f"pdf:  {pdf_path} ({engine})")
        else:
            print("warning: no PDF engine found (pip install weasyprint, or Node + playwright); HTML only.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
