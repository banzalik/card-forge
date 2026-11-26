# Built-in Templates

All templates share one layout, defined in `assets/card.css` and used by both the Python
renderer and the web designer:

- **Front:** a primary-colour header band holds the logo, issuer name, subtitle and a template
  badge. Below it come the holder name, the ID number in monospace, and a 2–3 column grid of
  `front.fields` plus effective and expiry dates. An optional photo (`branding.photoPath`)
  sits on the right. An accent stripe runs along the bottom edge.
- **Back:** optional magnetic stripe, then the header, contacts and fields as label/value rows,
  an optional signature strip, the legal notice and the barcode. A QR code sits to the right
  of the text; PDF417 and Code 128 run full width along the bottom.

| Slug | Badge | Holder label | ID label | Default barcode | Sample |
| --- | --- | --- | --- | --- | --- |
| `auto-insurance` | AUTO ID | Named Insured | Policy Number | `PDF417` | `assets/samples/auto-insurance.json` |
| `medical-doctor` | HEALTH ID | Member / Patient | Member ID | `QR` | `assets/samples/medical-doctor.json` |
| `membership-loyalty` | value of the field with `key: "tier"`, else MEMBER | Member | Member ID | `CODE128` | `assets/samples/membership.json` |
| `generic-id` | ID | Name | ID Number | `QR` | `assets/samples/generic-id.json` |

"Default barcode" is a recommendation for choosing `back.barcode.format`. The format in the
payload always wins.

## Recommended slots

### `auto-insurance`
- **Front:** carrier (`issuerName`), policy # (`idNumber`), named insured (`holderName`), effective/expiration
  dates, and `fields` for NAIC #, vehicle year/make/model, VIN and agent.
- **Back:** 24/7 claims hotline, roadside assistance (`contacts`), state statutory notice (`legalNotice`),
  and a PDF417 barcode carrying policy, name, dates and VIN.

### `medical-doctor`
- **Front:** hospital/clinic or plan (`issuerName`), practitioner/patient name, member ID or credentials, and
  `fields` for group # or NPI, plan, specialty/PCP and copays.
- **Back:** member services and nurse/triage lines, RxBIN / RxPCN / RxGRP (`fields`), and a QR code with the
  verification URL.

### `membership-loyalty`
- **Front:** organisation, member name, member ID, and `fields` with `key: "tier"` (rendered as the badge,
  not in the grid) plus home location. `effectiveDate` is shown as "Member Since".
- **Back:** facility hours, benefits summary, terms of use, an optional signature strip / mag stripe, and a
  Code 128 member number.

### `generic-id`
- **Front:** issuer, full name, ID #, issue/expiry dates, and up to 4 custom fields (6 fit, 4 read best).
- **Back:** custom header, contact list, freeform notice and a QR code.

## Content limits (so text fits the 3 mm safe zone)

| Item | Comfortable max |
| --- | --- |
| `issuerName` | ~32 characters |
| `holderName` | ~28 characters |
| `front.fields` value | ~22 characters (3-column grid) / ~30 (2-column) |
| back rows (`contacts` + `fields`) | 5 with a wide barcode, 6–7 with QR |
| `legalNotice` | ~220 characters |
| PDF417 payload | ~120 characters (the code gets dense beyond that) |

Proof with `--guides` and shorten content that collides. Text is never auto-shrunk.

## Custom templates

To add a template: add its slug to the `template` enum in `assets/schema.json` and to `TEMPLATES` /
`HOLDER_LABEL` / `ID_LABEL` in `scripts/cardforge_common.py` and `scripts/render.py`, plus `TEMPLATES` in
`web/src/cardforge.js`. Restyle through `assets/card.css`, keeping physical units (`mm`/`pt`).
