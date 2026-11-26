#!/usr/bin/env python3
"""Build Google Wallet "Add to Google Wallet" links (savetowallet JWT, RS256).

Environment:
    GOOGLE_WALLET_ISSUER_ID       numeric issuer id from the Google Pay & Wallet Console
    GOOGLE_SA_EMAIL               service-account e-mail (JWT `iss`)
    GOOGLE_SA_KEY_PEM             path to the service account's PEM private key
                                  (extract `private_key` from the JSON key file)
    GOOGLE_WALLET_ORIGINS         optional comma-separated origins allowed to show the button
Without a key, the unsigned claims are printed so they can be inspected.
The generic class (ISSUER_ID.cardforge_generic_v1) is included in the JWT, so
no separate REST call is needed for first-time issuance.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardforge_common import CardError, load_records, normalize, safe_id  # noqa: E402

G_BARCODE = {"PDF417": "PDF_417", "QR": "QR_CODE", "CODE128": "CODE_128"}
CLASS_SUFFIX = "cardforge_generic_v1"


def _ls(value: str) -> dict:
    return {"defaultValue": {"language": "en-US", "value": value}}


def generic_object(card: dict, issuer_id: str) -> dict:
    f, b, back = card["front"], card["branding"], card["back"]
    modules = []
    for x in f.get("fields", []):
        modules.append({"id": safe_id(x.get("key") or x["label"]).lower(), "header": x["label"], "body": x["value"]})
    if back.get("contacts"):
        modules.append({"id": "contacts", "header": back.get("header") or "Contacts",
                        "body": "\n".join(f"{c['label']}: {c['value']}" for c in back["contacts"])})
    for i, x in enumerate(back.get("fields") or []):
        modules.append({"id": f"back{i}", "header": x["label"], "body": x["value"]})
    if back.get("legalNotice"):
        modules.append({"id": "legal", "header": "Notice", "body": back["legalNotice"]})

    obj = {
        "id": f"{issuer_id}.{safe_id(f['idNumber'])}",
        "classId": f"{issuer_id}.{CLASS_SUFFIX}",
        "state": "ACTIVE",
        "hexBackgroundColor": b["primaryColor"],
        "cardTitle": _ls(f["issuerName"]),
        "header": _ls(f["holderName"]),
        "subheader": _ls(f"ID: {f['idNumber']}"),
        "textModulesData": modules,
    }
    if f.get("expirationDate"):
        obj["validTimeInterval"] = {"end": {"date": f"{f['expirationDate']}T23:59:59Z"}}
    bc = back.get("barcode")
    if bc:
        obj["barcode"] = {"type": G_BARCODE[bc["format"]], "value": bc["value"]}
        if bc.get("altText"):
            obj["barcode"]["alternateText"] = bc["altText"]
    return obj


def build_claims(cards: list[dict], issuer_id: str, sa_email: str, origins: list[str]) -> dict:
    claims = {
        "iss": sa_email,
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "payload": {
            "genericClasses": [{"id": f"{issuer_id}.{CLASS_SUFFIX}"}],
            "genericObjects": [generic_object(c, issuer_id) for c in cards],
        },
    }
    if origins:
        claims["origins"] = origins
    return claims


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_rs256(claims: dict, key_pem: str) -> str:
    if not shutil.which("openssl"):
        raise RuntimeError("openssl not found on PATH")
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode())
    signing_input = f"{header}.{body}".encode()
    sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_pem], input=signing_input,
                         capture_output=True, check=True).stdout
    return f"{header}.{body}.{_b64url(sig)}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build Google Wallet save links from CardForge payloads.")
    ap.add_argument("input")
    ap.add_argument("--template")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--one-link", action="store_true", help="Put every card in a single JWT/link")
    a = ap.parse_args(argv)
    src = Path(a.input)
    try:
        cards = [normalize(r, a.template, src.parent) for r in load_records(src)]
    except CardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    issuer = os.environ.get("GOOGLE_WALLET_ISSUER_ID", "ISSUER_ID")
    sa = os.environ.get("GOOGLE_SA_EMAIL", "cardforge-signer@project-id.iam.gserviceaccount.com")
    key = os.environ.get("GOOGLE_SA_KEY_PEM")
    origins = [o.strip() for o in os.environ.get("GOOGLE_WALLET_ORIGINS", "").split(",") if o.strip()]
    groups = [cards] if a.one_link else [[c] for c in cards]

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for group in groups:
        claims = build_claims(group, issuer, sa, origins)
        entry = {"ids": [c["front"]["idNumber"] for c in group]}
        if key and Path(key).is_file():
            entry["saveUrl"] = f"https://pay.google.com/gp/v/save/{sign_rs256(claims, key)}"
        else:
            entry["unsignedClaims"] = claims
        results.append(entry)
    path = out / f"{safe_id(src.stem)}-gwallet.json"
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    signed = all("saveUrl" in r for r in results)
    print(f"gwallet: {path} ({'signed save links' if signed else 'UNSIGNED claims; set GOOGLE_SA_KEY_PEM to sign'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
