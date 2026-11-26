---
name: card-forge
description: Generates double-sided CR80 credit-card-sized ID cards (auto insurance, medical/doctor ID, membership, generic ID) as printable PDFs with automatic front-to-back duplex print alignment, configurable cards-per-page sheets, Apple Wallet (.pkpass) bundles, and Google Wallet save links. Use when building card generation tools, creating insurance or medical ID cards, laying out multi-card duplex print sheets, calibrating a duplex printer, or generating mobile wallet passes.
license: MIT
compatibility: Python 3.9+ (stdlib only for imposition, rendering to HTML and wallet packaging). Optional - jsonschema (full validation), segno / pdf417gen / python-barcode (barcodes), WeasyPrint or Node 20+ with Playwright (PDF), openssl CLI (signing).
metadata:
  author: cardforge
  version: "1.0.0"
  standard: "ISO/IEC 7810 ID-1 (CR80)"
---

# CardForge

Generate standardized two-sided ID cards, duplex-aligned print sheets, and signed mobile
wallet passes from structured JSON or CSV records. All paths below are relative to this
skill's directory.

## 1. Core standards

- **Card geometry:** ISO/IEC 7810 ID-1 (CR80): `85.60 × 53.98 mm` (`3.370 × 2.125 in`),
  `3.18 mm` corner radius, `2.00 mm` bleed (`89.60 × 57.98 mm` bleed box).
- **Double-sided model:** every card has independent `front` and `back` surfaces.
- **Imposition:** 1, 2, 4, 8 or 10 cards per US Letter or A4 page. Page 2 (backs) is
  mirrored so physical duplex printing lines each back up with its front.

## 2. Workflow

### Step 1: Prepare and validate the data

1. Card payloads follow `assets/schema.json` (JSON Schema 2020-12). Start from a file in
   `assets/samples/`. `scripts/cardforge.py init <dir>` copies the samples plus a CSV
   example and a `.env.example`.
2. Input can be a single JSON object, a JSON array, `{"cards": [...]}`, or a CSV whose
   headers are dotted paths (`front.holderName`, `front.fields.0.label`, `back.barcode.value`).
3. Pick a template from `references/templates-catalog.md`: `auto-insurance`, `medical-doctor`,
   `membership-loyalty` or `generic-id`. Every script validates input and stops on the first
   invalid record, naming the card and the problems.

### Step 2: Plan the print sheet

| Option | Values | Notes |
| --- | --- | --- |
| `--paper` | `letter`, `a4` | |
| `--per-page` | `1`, `2`, `4`, `8`, `10` | `8` is the safe default for desktop printers |
| `--mode` | `batch`, `copies` | `batch`: one record per slot. `copies`: the first record fills the page |
| `--flip` | `long-edge`, `short-edge` | must match the printer's duplex setting |
| `--offset-x/-y` | mm | back-page calibration only; fronts never move |

Run `python3 scripts/impose.py --paper letter --per-page 8 --flip long-edge` for exact slot
coordinates. **Always pass any `warnings` it prints on to the user.** 10-up on Letter has
only 0.75 mm outer margins and needs borderless printing. The maths is in
`references/imposition-spec.md`.

### Step 3: Render

```bash
# Duplex PDF sheet (HTML is always written; PDF via WeasyPrint or Chromium/Playwright)
python3 scripts/cardforge.py generate cards.json --format pdf --per-page 8 --mode batch --out dist

# Apple Wallet: signed .pkpass when APPLE_* env vars point at PEM files, else unsigned .pkpass.zip
python3 scripts/cardforge.py generate cards.json --format pkpass --out dist

# Google Wallet: signed save links when GOOGLE_SA_KEY_PEM is set, else unsigned claims JSON
python3 scripts/cardforge.py generate cards.json --format gwallet --out dist

# Two-page duplex calibration target with mm rulers
python3 scripts/cardforge.py calibrate --paper letter --flip long-edge --out calibration.pdf
```

The individual scripts (`render.py`, `build_pkpass.py`, `gwallet_link.py`, `impose.py`)
take the same options if you need only one stage.

- **PDF:** fronts on odd pages, backs on even pages, with a page break after every sheet.
  Barcodes are inline vector SVG (`PDF417`, `QR`, `CODE128`). Crop marks are drawn on the
  sheet perimeter, aligned to every trim line and kept outside the bleed. `--guides` adds
  dashed rounded-corner trim outlines for proofing only.
- **Apple Wallet:** generic pass style, mapped as in `references/wallet-mapping.md`.
  `manifest.json` holds SHA-1 digests and `signature` is a detached PKCS#7 (DER) made with `openssl smime`.
- **Google Wallet:** an RS256 `savetowallet` JWT that embeds both the generic class and the
  generic object(s), served as `https://pay.google.com/gp/v/save/<JWT>`.

### Step 4: Check before handing over

1. Open the generated HTML or PDF and confirm no barcode shows the dashed "pip install" placeholder.
   If one does, install the missing library.
2. Tell the user to print at **100% / actual size** (never "fit to page"), duplex on, with
   the flip edge used at generation time.
3. For a new printer, print the calibration target first. Convert the measured drift
   to `--offset-x/-y` using the rule printed on the target:
   - long-edge: `offsetX = -dx`, `offsetY = +dy`
   - short-edge: `offsetX = +dx`, `offsetY = -dy`

   Here `dx`/`dy` are measured from the front side, with right and down as positive.

## 3. Edge cases

- **Serving `.pkpass`:** return `Content-Type: application/vnd.apple.pkpass`. Tell users to
  open the link in iOS Safari, because many in-app webviews will not hand passes to Wallet.
- **Unsigned outputs** are for inspection only. Wallet apps reject them, so say so and never
  present them as installable.
- **Secrets:** signing keys come from environment variables pointing at PEM files. Never
  write keys into payloads, HTML, or the static web designer.
- **Health and insurance data:** card payloads may contain PHI/PII. Keep output local
  unless the user asks otherwise.
- **Interactive use:** `scripts/cardforge.py serve` serves the browser designer (from
  `../web/dist`) plus `GET /api/templates` and `POST /api/generate?format=pdf|pkpass|gwallet`.
  It binds to 127.0.0.1 by default. Requests cannot set image paths on the server.
