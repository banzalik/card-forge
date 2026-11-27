#!/usr/bin/env python3
"""cardforge — one CLI over the CardForge scripts.

    cardforge init [dir]
    cardforge templates
    cardforge calibrate --paper letter --flip long-edge --out ./calibration.pdf
    cardforge generate cards.json --format pdf|pkpass|gwallet|all --per-page 8 --out dist
    cardforge serve --port 3000 [--static web/dist]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_pkpass  # noqa: E402
import gwallet_link  # noqa: E402
import render  # noqa: E402
from cardforge_common import SKILL_DIR, TEMPLATES, CardError, normalize  # noqa: E402
from impose import FLIPS, GRID_PRESETS, PAPER_SIZES  # noqa: E402

SAMPLES = SKILL_DIR / "assets" / "samples"
MAX_BODY = 2 * 1024 * 1024

ENV_EXAMPLE = """\
# Apple Wallet signing (PEM file paths)
APPLE_PASS_TYPE_ID=pass.com.example.id
APPLE_TEAM_ID=ABCDE12345
APPLE_CERT_PEM=./certs/pass.pem
APPLE_KEY_PEM=./certs/pass.key
APPLE_KEY_PASSWORD=
APPLE_WWDR_PEM=./certs/wwdr.pem

# Google Wallet (service-account private key extracted to PEM)
GOOGLE_WALLET_ISSUER_ID=3388000000000000000
GOOGLE_SA_EMAIL=cardforge-signer@your-project.iam.gserviceaccount.com
GOOGLE_SA_KEY_PEM=./certs/google-sa.pem
GOOGLE_WALLET_ORIGINS=
"""

CSV_EXAMPLE = """\
template,front.issuerName,front.subtitle,front.holderName,front.idNumber,front.effectiveDate,front.expirationDate,front.fields.0.label,front.fields.0.value,front.fields.1.label,front.fields.1.value,back.header,back.contacts.0.label,back.contacts.0.value,back.legalNotice,back.barcode.format,back.barcode.value
generic-id,Northgate Makerspace,Volunteer Staff,Riley Chen,NGM-V-0042,2026-09-01,2027-08-31,Role,Shop Steward,Access,Wood · Metal,If found please return,Front desk,(206) 555-0110,Property of Northgate Makerspace.,QR,NGM-V-0042
generic-id,Northgate Makerspace,Volunteer Staff,Avery Brooks,NGM-V-0043,2026-09-01,2027-08-31,Role,Instructor,Access,Electronics,If found please return,Front desk,(206) 555-0110,Property of Northgate Makerspace.,QR,NGM-V-0043
"""


# --------------------------------------------------------------------------- commands
def cmd_init(a) -> int:
    root = Path(a.dir)
    root.mkdir(parents=True, exist_ok=True)
    for f in SAMPLES.glob("*.json"):
        dest = root / f.name
        if not dest.exists():
            shutil.copy(f, dest)
    for name, text in ((".env.example", ENV_EXAMPLE), ("cards.csv", CSV_EXAMPLE)):
        dest = root / name
        if not dest.exists():
            dest.write_text(text, encoding="utf-8")
    print(f"initialized {root.resolve()}")
    for p in sorted(root.iterdir()):
        print(f"  {p.name}")
    return 0


def templates_payload() -> list[dict]:
    out = []
    sample_for = {"membership-loyalty": "membership"}
    for slug, meta in TEMPLATES.items():
        sample_file = SAMPLES / f"{sample_for.get(slug, slug)}.json"
        out.append({
            "slug": slug,
            "defaultBarcode": meta["barcode"],
            "requiredFields": ["front.issuerName", "front.holderName", "front.idNumber"],
            "sample": json.loads(sample_file.read_text(encoding="utf-8")) if sample_file.exists() else None,
        })
    return out


def cmd_templates(a) -> int:
    for t in templates_payload():
        print(f"{t['slug']:<20} barcode={t['defaultBarcode']:<8} required: {', '.join(t['requiredFields'])}")
    return 0


def _render_args(a, extra: list[str]) -> list[str]:
    args = ["--paper", a.paper, "--flip", a.flip, "--per-page", str(a.per_page),
            "--offset-x", str(a.offset_x), "--offset-y", str(a.offset_y)]
    return args + extra


def cmd_calibrate(a) -> int:
    out = Path(a.out)
    out_dir, name = (out.parent, out.stem) if out.suffix.lower() == ".pdf" else (out, None)
    extra = ["--calibrate", "--out", str(out_dir)] + (["--name", name] if name else [])
    return render.main(_render_args(a, extra))


def cmd_generate(a) -> int:
    formats = ["pdf", "pkpass", "gwallet"] if a.format == "all" else [a.format]
    rc = 0
    tpl = ["--template", a.template] if a.template else []
    if "pdf" in formats:
        extra = [a.input, "--mode", a.mode, "--out", a.out, *tpl]
        extra += ["--bleed" if a.bleed else "--no-bleed"]
        extra += ["--cut-lines" if a.cut_lines else "--no-cut-lines"]
        rc |= render.main(_render_args(a, extra))
    if "pkpass" in formats:
        rc |= build_pkpass.main([a.input, "--out", a.out, *tpl])
    if "gwallet" in formats:
        rc |= gwallet_link.main([a.input, "--out", a.out, *tpl])
    return rc


# --------------------------------------------------------------------------- serve
def make_handler(static_dir: Path | None):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw):
            super().__init__(*args, directory=str(static_dir) if static_dir else None, **kw)

        def log_message(self, fmt, *args):  # quieter
            sys.stderr.write("serve: " + (fmt % args) + "\n")

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            path = urlparse(self.path).path
            if path.rstrip("/") == "/api/templates":
                return self._json(200, templates_payload())
            if static_dir is None:
                return self._send(404, b"No static site built. Run `npm ci && npm run build` in web/.", "text/plain")
            return super().do_GET()

        def do_POST(self):
            url = urlparse(self.path)
            if url.path.rstrip("/") != "/api/generate":
                return self._json(404, {"error": "not found"})
            fmt = (parse_qs(url.query).get("format") or ["pdf"])[0]
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._json(413 if length > MAX_BODY else 400, {"error": "body required (max 2 MiB)"})
            try:
                body = json.loads(self.rfile.read(length))
                opts = {k: body.pop(k) for k in ("perPage", "paper", "flip", "offsetX", "offsetY", "mode") if k in body}
                # Never let a web request point the renderer at files on this machine.
                for k in ("logoPath", "iconPath", "photoPath"):
                    (body.get("branding") or {}).pop(k, None)
                card = normalize(body)
            except (json.JSONDecodeError, CardError) as e:
                return self._json(400, {"error": str(e)})
            try:
                return self._generate(fmt, card, opts)
            except Exception as e:  # surface failure to the caller rather than hanging
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def _generate(self, fmt: str, card: dict, opts: dict):
            with tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                if fmt == "pkpass":
                    path = build_pkpass.build_pkpass(card, tmpdir)
                    signed = path.suffix == ".pkpass"
                    ctype = "application/vnd.apple.pkpass" if signed else "application/zip"
                    return self._send(200, path.read_bytes(), ctype,
                                      {"Content-Disposition": f'attachment; filename="{path.name}"'})
                if fmt == "gwallet":
                    issuer = os.environ.get("GOOGLE_WALLET_ISSUER_ID", "ISSUER_ID")
                    sa = os.environ.get("GOOGLE_SA_EMAIL", "cardforge-signer@project-id.iam.gserviceaccount.com")
                    key = os.environ.get("GOOGLE_SA_KEY_PEM")
                    origins = [o.strip() for o in os.environ.get("GOOGLE_WALLET_ORIGINS", "").split(",") if o.strip()]
                    claims = gwallet_link.build_claims([card], issuer, sa, origins)
                    if key and Path(key).is_file():
                        return self._json(200, {"saveUrl": f"https://pay.google.com/gp/v/save/{gwallet_link.sign_rs256(claims, key)}"})
                    return self._json(200, {"saveUrl": None, "unsignedClaims": claims})
                if fmt == "pdf":
                    src = tmpdir / "card.json"
                    src.write_text(json.dumps(card), encoding="utf-8")
                    args = [str(src), "--out", str(tmpdir), "--name", "cards",
                            "--paper", str(opts.get("paper", "letter")), "--per-page", str(opts.get("perPage", 8)),
                            "--flip", str(opts.get("flip", "long-edge")), "--mode", str(opts.get("mode", "copies")),
                            "--offset-x", str(float(opts.get("offsetX", 0))), "--offset-y", str(float(opts.get("offsetY", 0))),
                            "--cut-lines" if opts.get("cutLines", True) else "--no-cut-lines"]
                    try:
                        render.main(args)
                    except SystemExit as e:  # argparse rejected an option
                        return self._json(400, {"error": f"invalid print options ({e})"})
                    pdf = tmpdir / "cards.pdf"
                    if not pdf.exists():
                        return self._json(501, {"error": "no PDF engine available on the server"})
                    return self._send(200, pdf.read_bytes(), "application/pdf",
                                      {"Content-Disposition": 'attachment; filename="cards.pdf"'})
                return self._json(400, {"error": "format must be pdf, pkpass or gwallet"})

    return Handler


def cmd_serve(a) -> int:
    static = Path(a.static) if a.static else (SKILL_DIR.parent / "web" / "dist")
    static_dir = static if (static / "index.html").exists() else None
    if static_dir is None:
        print(f"note: {static} not built; API only. Build it with: cd web && npm ci && npm run build", file=sys.stderr)
    httpd = ThreadingHTTPServer((a.host, a.port), make_handler(static_dir))
    print(f"CardForge serving on http://{a.host}:{a.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


# --------------------------------------------------------------------------- argparse
def _sheet_opts(p):
    p.add_argument("--paper", default="letter", choices=sorted(PAPER_SIZES))
    p.add_argument("--per-page", type=int, default=8, choices=sorted(GRID_PRESETS))
    p.add_argument("--flip", default="long-edge", choices=FLIPS)
    p.add_argument("--offset-x", type=float, default=0.0)
    p.add_argument("--offset-y", type=float, default=0.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cardforge", description="CR80 double-sided card generator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="Create a workspace with sample JSON/CSV and .env.example")
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=cmd_init)

    sub.add_parser("templates", help="List built-in templates").set_defaults(fn=cmd_templates)

    p = sub.add_parser("calibrate", help="Two-page duplex calibration target")
    _sheet_opts(p)
    p.add_argument("--out", default="calibration.pdf", help="PDF path or output directory")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("generate", help="Generate PDF sheets and/or wallet passes")
    p.add_argument("input")
    p.add_argument("--template", choices=sorted(TEMPLATES))
    p.add_argument("--format", default="pdf", choices=["pdf", "pkpass", "gwallet", "all"])
    p.add_argument("--mode", default="batch", choices=["batch", "copies"])
    p.add_argument("--bleed", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--cut-lines", action=argparse.BooleanOptionalAction, default=True,
                   help="Dashed full-length cut lines on the front sheet (default on)")
    p.add_argument("--out", default="dist")
    _sheet_opts(p)
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("serve", help="Local designer + wallet API")
    p.add_argument("--port", type=int, default=3000)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--static", help="Directory of the built web designer (default: ../web/dist)")
    p.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
