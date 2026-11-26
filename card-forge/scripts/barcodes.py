"""Inline SVG barcode generation (PDF417, QR, CODE128).

Uses optional pure-Python libraries:  segno (QR), pdf417gen (PDF417),
python-barcode (CODE128).  If a library is missing, a labelled placeholder
is returned so layout still renders and the gap is obvious on proof.
"""
from __future__ import annotations

from html import escape


def _placeholder(fmt: str, value: str, reason: str) -> str:
    return (
        '<svg class="barcode-missing" viewBox="0 0 100 30" preserveAspectRatio="none">'
        '<rect x="0.5" y="0.5" width="99" height="29" fill="none" stroke="#999" stroke-dasharray="2 2"/>'
        f'<text x="50" y="13" font-size="6" text-anchor="middle" fill="#666">{escape(fmt)} barcode</text>'
        f'<text x="50" y="22" font-size="4" text-anchor="middle" fill="#999">{escape(reason)}</text>'
        "</svg>"
    )


def qr_svg(value: str) -> str:
    try:
        import segno  # type: ignore
    except ImportError:
        return _placeholder("QR", value, "pip install segno")
    qr = segno.make(value, error="m", micro=False)
    return qr.svg_inline(scale=1, border=0, omitsize=True, dark="#000")


def pdf417_svg(value: str, columns: int = 6, row_ratio: int = 3) -> str:
    try:
        import pdf417gen  # type: ignore
        from pdf417gen.rendering import barcode_size, modules  # type: ignore
    except ImportError:
        return _placeholder("PDF417", value, "pip install pdf417gen")
    codes = pdf417gen.encode(value, columns=columns, security_level=2)
    width, height = barcode_size(codes)
    rects = "".join(
        f'<rect x="{x}" y="{y * row_ratio}" width="1" height="{row_ratio}"/>' for x, y in modules(codes)
    )
    return (
        f'<svg viewBox="0 0 {width} {height * row_ratio}" preserveAspectRatio="none" shape-rendering="crispEdges">'
        f'<g fill="#000">{rects}</g></svg>'
    )


def code128_svg(value: str) -> str:
    try:
        import barcode  # type: ignore
    except ImportError:
        return _placeholder("CODE128", value, "pip install python-barcode")
    bits = barcode.get("code128", value).build()[0]
    rects, x, n = [], 0, len(bits)
    while x < n:
        if bits[x] == "1":
            start = x
            while x < n and bits[x] == "1":
                x += 1
            rects.append(f'<rect x="{start}" y="0" width="{x - start}" height="1"/>')
        else:
            x += 1
    return (
        f'<svg viewBox="0 0 {n} 1" preserveAspectRatio="none" shape-rendering="crispEdges">'
        f'<g fill="#000">{"".join(rects)}</g></svg>'
    )


def barcode_svg(fmt: str, value: str) -> str:
    if fmt == "QR":
        return qr_svg(value)
    if fmt == "PDF417":
        return pdf417_svg(value)
    if fmt == "CODE128":
        return code128_svg(value)
    raise ValueError(f"Unsupported barcode format: {fmt}")
