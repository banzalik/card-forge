"""Shared helpers for CardForge scripts: loading, defaults, validation."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_DIR / "assets" / "schema.json"

TEMPLATES = {
    "auto-insurance": {"barcode": "PDF417", "badge": "AUTO ID"},
    "medical-doctor": {"barcode": "QR", "badge": "HEALTH ID"},
    "membership-loyalty": {"barcode": "CODE128", "badge": "MEMBER"},
    "generic-id": {"barcode": "QR", "badge": "ID"},
}

DEFAULT_BRANDING = {
    "primaryColor": "#0F172A",
    "accentColor": "#2563EB",
    "textColor": "#FFFFFF",
}

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class CardError(ValueError):
    pass


# --------------------------------------------------------------------------- loading
def _set_path(obj: dict, path: str, value):
    """Set a dotted path like front.fields.0.label, creating dicts/lists as needed."""
    parts = path.split(".")
    cur = obj
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        nxt_is_index = not last and parts[i + 1].isdigit()
        if isinstance(cur, list):
            idx = int(part)
            while len(cur) <= idx:
                cur.append({} if not nxt_is_index else [])
            if last:
                cur[idx] = value
            else:
                cur = cur[idx]
        else:
            if last:
                cur[part] = value
            else:
                cur = cur.setdefault(part, [] if nxt_is_index else {})


def _coerce(value: str):
    v = value.strip()
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def _prune(obj):
    """Drop empty strings, dicts and lists (CSV rows padded with blank columns)."""
    if isinstance(obj, dict):
        out = {k: _prune(v) for k, v in obj.items() if v != ""}
        return {k: v for k, v in out.items() if v not in ({}, [])}
    if isinstance(obj, list):
        items = [_prune(v) for v in obj]
        return [v for v in items if v not in ({}, [], "")]
    return obj


def load_records(path: str | Path) -> list[dict]:
    """Load one or many card payloads from .json (object or array) or .csv (dotted headers)."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        records = []
        with p.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                rec: dict = {}
                for header, value in row.items():
                    if header is None or value is None or value.strip() == "":
                        continue
                    _set_path(rec, header.strip(), _coerce(value))
                records.append(_prune(rec))
        return records
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "cards" in data and isinstance(data["cards"], list):
        data = data["cards"]
    return data if isinstance(data, list) else [data]


# --------------------------------------------------------------------------- validation
def validate(record: dict) -> list[str]:
    """Return a list of human-readable problems (empty list = valid)."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return _validate_minimal(record)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    return [
        f"{'/'.join(str(x) for x in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path))
    ]


def _validate_minimal(record: dict) -> list[str]:
    errs = []
    if not isinstance(record, dict):
        return ["<root>: payload must be an object"]
    for key in ("template", "front", "back"):
        if key not in record:
            errs.append(f"<root>: '{key}' is a required property")
    if record.get("template") not in TEMPLATES:
        errs.append(f"template: must be one of {list(TEMPLATES)}")
    front = record.get("front") or {}
    for key in ("issuerName", "holderName", "idNumber"):
        if not front.get(key):
            errs.append(f"front: '{key}' is a required property")
    if len(front.get("fields", [])) > 6:
        errs.append("front/fields: at most 6 items")
    for k, v in (record.get("branding") or {}).items():
        if k.endswith("Color") and not HEX.match(str(v)):
            errs.append(f"branding/{k}: must match #RRGGBB")
    bc = (record.get("back") or {}).get("barcode")
    if bc and bc.get("format") not in ("PDF417", "QR", "CODE128"):
        errs.append("back/barcode/format: must be PDF417, QR or CODE128")
    return errs


def normalize(record: dict, template_override: str | None = None, base_dir: Path | None = None) -> dict:
    """Validate, apply template + branding defaults, resolve asset paths. Raises CardError."""
    rec = json.loads(json.dumps(record))  # deep copy
    if template_override:
        rec["template"] = template_override
    problems = validate(rec)
    if problems:
        ident = (rec.get("front") or {}).get("idNumber", "?")
        raise CardError(f"Card {ident} is invalid:\n  - " + "\n  - ".join(problems))
    rec["branding"] = {**DEFAULT_BRANDING, **(rec.get("branding") or {})}
    rec["back"] = rec.get("back") or {}
    if base_dir:
        for key in ("logoPath", "iconPath", "photoPath"):
            v = rec["branding"].get(key)
            if v and not Path(v).is_absolute():
                rec["branding"][key] = str((base_dir / v).resolve())
    return rec


def safe_id(value: str) -> str:
    """Identifier safe for filenames and Google Wallet object ids ([A-Za-z0-9._-])."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("_") or "card"
