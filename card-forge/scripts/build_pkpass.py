#!/usr/bin/env python3
"""Build an Apple Wallet .pkpass (generic style) from a CardForge payload.

Signing uses the `openssl` CLI (PKCS#7 detached, DER) with:
    APPLE_CERT_PEM   Pass Type ID certificate (PEM path)
    APPLE_KEY_PEM    its private key (PEM path; APPLE_KEY_PASSWORD if encrypted)
    APPLE_WWDR_PEM   Apple WWDR intermediate certificate (PEM path)
    APPLE_PASS_TYPE_ID, APPLE_TEAM_ID   identifiers baked into pass.json
Without certificates, an unsigned `<id>.pkpass.zip` inspection bundle is written
instead (Wallet will refuse to open it, by design).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardforge_common import CardError, load_records, normalize, safe_id  # noqa: E402

PK_BARCODE = {"PDF417": "PKBarcodeFormatPDF417", "QR": "PKBarcodeFormatQR", "CODE128": "PKBarcodeFormatCode128"}
MAX_AUX = 4  # generic passes show at most 4 auxiliary fields; the rest go to the back


def _hex_to_rgb(h: str) -> str:
    h = h.lstrip("#")
    return f"rgb({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"


def _solid_png(size: int, hex_color: str) -> bytes:
    """Minimal solid-colour PNG (stdlib only) used when no icon is supplied."""
    h = hex_color.lstrip("#")
    rgb = bytes(int(h[i:i + 2], 16) for i in (0, 2, 4))
    raw = b"".join(b"\x00" + rgb * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def build_pass_json(card: dict, pass_type_id: str, team_id: str) -> dict:
    f, b, back = card["front"], card["branding"], card["back"]
    fields = [
        {"key": x.get("key") or f"f{i}", "label": x["label"].upper(), "value": x["value"]}
        for i, x in enumerate(f.get("fields", []))
    ]
    aux, overflow = fields[:MAX_AUX], fields[MAX_AUX:]

    secondary = [{"key": "id", "label": "ID / POLICY #", "value": f["idNumber"]}]
    if f.get("effectiveDate"):
        secondary.append({"key": "eff", "label": "EFFECTIVE", "value": f"{f['effectiveDate']}T00:00:00Z",
                          "dateStyle": "PKDateStyleShort", "ignoresTimeZone": True})
    header = []
    if f.get("expirationDate"):
        header.append({"key": "exp", "label": "EXPIRES", "value": f"{f['expirationDate']}T00:00:00Z",
                       "dateStyle": "PKDateStyleShort", "ignoresTimeZone": True})

    back_fields = []
    for i, c in enumerate(back.get("contacts") or []):
        back_fields.append({"key": f"contact{i}", "label": c["label"], "value": c["value"]})
    for i, x in enumerate(back.get("fields") or []):
        back_fields.append({"key": f"back{i}", "label": x["label"], "value": x["value"]})
    for x in overflow:
        back_fields.append({**x, "key": f"more_{x['key']}"})
    if back.get("legalNotice"):
        back_fields.append({"key": "legal", "label": "TERMS & LEGAL NOTICE", "value": back["legalNotice"]})

    p = {
        "formatVersion": 1,
        "passTypeIdentifier": pass_type_id,
        "teamIdentifier": team_id,
        "organizationName": f["issuerName"],
        "serialNumber": f["idNumber"],
        "description": f.get("subtitle") or f"{f['issuerName']} card",
        "logoText": f["issuerName"],
        "backgroundColor": _hex_to_rgb(b["primaryColor"]),
        "foregroundColor": _hex_to_rgb(b["textColor"]),
        "labelColor": "rgb(203, 213, 225)",
        "generic": {
            "headerFields": header,
            "primaryFields": [{"key": "holder", "label": "CARDHOLDER", "value": f["holderName"]}],
            "secondaryFields": secondary,
            "auxiliaryFields": aux,
            "backFields": back_fields,
        },
    }
    if f.get("expirationDate"):
        p["expirationDate"] = f"{f['expirationDate']}T23:59:59Z"
    bc = back.get("barcode")
    if bc:
        entry = {"message": bc["value"], "format": PK_BARCODE[bc["format"]], "messageEncoding": "iso-8859-1"}
        if bc.get("altText"):
            entry["altText"] = bc["altText"]
        p["barcodes"] = [entry]
    return p


def _image_files(card: dict) -> dict[str, bytes]:
    b = card["branding"]
    files: dict[str, bytes] = {}
    icon = b.get("iconPath")
    if icon and Path(icon).is_file():
        data = Path(icon).read_bytes()
        files["icon.png"] = data
        files["icon@2x.png"] = data
    else:
        files["icon.png"] = _solid_png(29, b["accentColor"])
        files["icon@2x.png"] = _solid_png(58, b["accentColor"])
    logo = b.get("logoPath")
    if logo and Path(logo).is_file() and logo.lower().endswith(".png"):
        files["logo.png"] = Path(logo).read_bytes()
    return files


def _sign(manifest: bytes, cert: str, key: str, wwdr: str, password: str | None) -> bytes:
    if not shutil.which("openssl"):
        raise RuntimeError("openssl not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        mpath, spath = Path(tmp, "manifest.json"), Path(tmp, "signature")
        mpath.write_bytes(manifest)
        cmd = ["openssl", "smime", "-binary", "-sign", "-signer", cert, "-inkey", key, "-certfile", wwdr,
               "-in", str(mpath), "-out", str(spath), "-outform", "DER"]
        env = dict(os.environ)
        if password:
            cmd += ["-passin", "env:APPLE_KEY_PASSWORD"]
            env["APPLE_KEY_PASSWORD"] = password
        subprocess.run(cmd, check=True, capture_output=True, env=env)
        return spath.read_bytes()


def build_pkpass(card: dict, out_dir: Path) -> Path:
    pass_type = os.environ.get("APPLE_PASS_TYPE_ID", "pass.com.cardforge.id")
    team = os.environ.get("APPLE_TEAM_ID", "TEAMID1234")
    files = {"pass.json": json.dumps(build_pass_json(card, pass_type, team), indent=2, ensure_ascii=False).encode()}
    files.update(_image_files(card))
    manifest = json.dumps({n: hashlib.sha1(d).hexdigest() for n, d in files.items()}, indent=2).encode()
    files["manifest.json"] = manifest

    cert, key, wwdr = (os.environ.get(k) for k in ("APPLE_CERT_PEM", "APPLE_KEY_PEM", "APPLE_WWDR_PEM"))
    signed = all(v and Path(v).is_file() for v in (cert, key, wwdr))
    if signed:
        files["signature"] = _sign(manifest, cert, key, wwdr, os.environ.get("APPLE_KEY_PASSWORD"))

    name = safe_id(card["front"]["idNumber"]) + (".pkpass" if signed else ".pkpass.zip")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    out.write_bytes(buf.getvalue())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build Apple Wallet passes from CardForge payloads.")
    ap.add_argument("input")
    ap.add_argument("--template")
    ap.add_argument("--out", default="dist")
    a = ap.parse_args(argv)
    src = Path(a.input)
    try:
        cards = [normalize(r, a.template, src.parent) for r in load_records(src)]
    except CardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for card in cards:
        path = build_pkpass(card, Path(a.out))
        kind = "signed" if path.suffix == ".pkpass" else "UNSIGNED inspection bundle (set APPLE_* env vars to sign)"
        print(f"pkpass: {path} ({kind})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
