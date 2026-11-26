# Wallet Mapping

Implemented by `scripts/build_pkpass.py` (Apple) and `scripts/gwallet_link.py` (Google).

## 1. Apple Wallet (`.pkpass`, `generic` style)

A `.pkpass` is a ZIP containing:

| File | Notes |
| --- | --- |
| `pass.json` | mapping below |
| `icon.png`, `icon@2x.png` | 29×29 and 58×58 px. Required. Generated as an accent-colour square when `branding.iconPath` is absent |
| `logo.png` | optional, ≤160×50 pt, from `branding.logoPath` (PNG only) |
| `manifest.json` | `{ filename: sha1-hex }` for every file above |
| `signature` | PKCS#7 detached signature of `manifest.json`, DER. Pass certificate + key + Apple WWDR intermediate |

Signing command used:

```bash
openssl smime -binary -sign -signer pass.pem -inkey pass.key -certfile wwdr.pem \
  -in manifest.json -out signature -outform DER
```

| Env var | Purpose |
| --- | --- |
| `APPLE_PASS_TYPE_ID` | `passTypeIdentifier` (must match the certificate) |
| `APPLE_TEAM_ID` | `teamIdentifier` |
| `APPLE_CERT_PEM`, `APPLE_KEY_PEM`, `APPLE_WWDR_PEM` | PEM file paths |
| `APPLE_KEY_PASSWORD` | key passphrase, if any (passed to openssl via env, not argv) |

With any of the three PEMs missing, the output is `<id>.pkpass.zip`, unsigned. Wallet rejects
it, so use it for inspection only.

### Field mapping

| pass.json | Source |
| --- | --- |
| `organizationName` | `front.issuerName` |
| `serialNumber` | `front.idNumber` (must be unique per pass type) |
| `description` | `front.subtitle`, else `"<issuer> card"` (required by Apple) |
| `logoText` | `front.issuerName` |
| `backgroundColor` / `foregroundColor` | `branding.primaryColor` / `branding.textColor` as `rgb(r, g, b)` |
| `labelColor` | `rgb(203, 213, 225)` |
| `expirationDate` | `front.expirationDate` + `T23:59:59Z` (Wallet greys the pass out afterwards) |
| `generic.headerFields` | `EXPIRES` ← `front.expirationDate` (`PKDateStyleShort`, `ignoresTimeZone`) |
| `generic.primaryFields` | `CARDHOLDER` ← `front.holderName` |
| `generic.secondaryFields` | `ID / POLICY #` ← `front.idNumber`, `EFFECTIVE` ← `front.effectiveDate` |
| `generic.auxiliaryFields` | first **4** of `front.fields` (the generic style shows at most 4) |
| `generic.backFields` | `back.contacts`, then `back.fields`, then `front.fields` beyond 4, then `TERMS & LEGAL NOTICE` ← `back.legalNotice` |
| `barcodes[0]` | `back.barcode` → `PKBarcodeFormatPDF417` / `PKBarcodeFormatQR` / `PKBarcodeFormatCode128`, `messageEncoding: iso-8859-1`, `altText` |

Code 128 does not display on Apple Watch. Prefer QR or PDF417 when watch support matters.

### Serving

`Content-Type: application/vnd.apple.pkpass`. Open the link in iOS Safari, because third-party
in-app browsers often swallow the download instead of offering "Add to Wallet".

## 2. Google Wallet (`savetowallet` JWT)

| Env var | Purpose |
| --- | --- |
| `GOOGLE_WALLET_ISSUER_ID` | numeric issuer id (Google Pay & Wallet Console) |
| `GOOGLE_SA_EMAIL` | service-account e-mail → `iss` |
| `GOOGLE_SA_KEY_PEM` | PEM file holding the service account's `private_key` |
| `GOOGLE_WALLET_ORIGINS` | optional, comma-separated, for JWTs used by the web button |

Claims (signed RS256 with `openssl dgst -sha256 -sign`):

```json
{
  "iss": "<GOOGLE_SA_EMAIL>",
  "aud": "google",
  "typ": "savetowallet",
  "iat": 1795714020,
  "payload": {
    "genericClasses": [{ "id": "ISSUER_ID.cardforge_generic_v1" }],
    "genericObjects": [{
      "id": "ISSUER_ID.<safe idNumber>",
      "classId": "ISSUER_ID.cardforge_generic_v1",
      "state": "ACTIVE",
      "hexBackgroundColor": "<branding.primaryColor>",
      "cardTitle": { "defaultValue": { "language": "en-US", "value": "<front.issuerName>" } },
      "header":    { "defaultValue": { "language": "en-US", "value": "<front.holderName>" } },
      "subheader": { "defaultValue": { "language": "en-US", "value": "ID: <front.idNumber>" } },
      "textModulesData": [
        { "id": "<field key>", "header": "<front.fields[].label>", "body": "<value>" },
        { "id": "contacts", "header": "<back.header>", "body": "Label: value\n…" },
        { "id": "back0", "header": "<back.fields[].label>", "body": "<value>" },
        { "id": "legal", "header": "Notice", "body": "<back.legalNotice>" }
      ],
      "validTimeInterval": { "end": { "date": "<front.expirationDate>T23:59:59Z" } },
      "barcode": { "type": "PDF_417 | QR_CODE | CODE_128", "value": "<back.barcode.value>", "alternateText": "<altText>" }
    }]
  }
}
```

The link is `https://pay.google.com/gp/v/save/<JWT>`.

- Object ids may only contain `[A-Za-z0-9._-]`. Other characters in `idNumber` become `_`.
- The class is embedded in the JWT, so first-time issuance needs no separate REST call. To
  restyle an existing class, update it through the Wallet REST API.
- Long JWTs can exceed URL limits in some browsers. Keep one card per link (the default) unless
  `--one-link` is wanted.
- Without `GOOGLE_SA_KEY_PEM`, the script writes the **unsigned** claims for inspection.
