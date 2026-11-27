# CardForge

Double-sided **CR80 (ISO/IEC 7810 ID-1)** cards, such as auto-insurance, health/medical,
membership and generic IDs. CardForge produces:

- **Duplex-aligned print sheets** (1/2/4/8/10-up on US Letter or A4). Backs are mirrored for long- or short-edge flip, with per-printer calibration offsets, bleed and crop marks.
- **Apple Wallet** `.pkpass` (generic style, PKCS#7-signed with `openssl`).
- **Google Wallet** "save" links (RS256 `savetowallet` JWT).
- A **browser designer** you can publish on **GitHub Pages**. It runs entirely client-side, so card data never leaves the browser.

```
card-forge/                 Agent Skill package (agentskills.io layout)
├── SKILL.md
├── scripts/                impose.py · render.py · build_pkpass.py · gwallet_link.py · cardforge.py (CLI)
├── references/             imposition-spec.md · wallet-mapping.md · templates-catalog.md
└── assets/                 schema.json · card.css · samples/*.json
web/                        static designer → GitHub Pages
tests/                      unittest suite + JS/Python imposition parity check
.github/workflows/          pages.yml (deploy) · test.yml (CI)
```

## Quick start (CLI)

```bash
pip install jsonschema segno pdf417gen python-barcode   # all optional, but recommended
```

```bash
python3 card-forge/scripts/cardforge.py generate card-forge/assets/samples/auto-insurance.json --format pdf --per-page 8 --mode copies --out dist
```

```bash
python3 card-forge/scripts/cardforge.py calibrate --paper letter --flip long-edge --out dist/calibration.pdf
```

For PDF output you need **WeasyPrint** (`pip install weasyprint`) or **Node + Playwright**
(`npm i -g playwright && npx playwright install chromium`). Without either, you get print-ready
HTML that any browser can print. Wallet signing reads PEM paths from environment variables;
see `cardforge init` for a `.env.example` and `card-forge/references/wallet-mapping.md`.

Print at **100% / actual size**, with duplex on and the same flip edge you generated for.

## Publish the designer to GitHub Pages

The workflow `.github/workflows/pages.yml` builds `web/` and deploys it with the official
Pages actions.

1. In the repository, open **Settings → Pages → Build and deployment** and set **Source** to **GitHub Actions**.
2. Push to `main`, or run **Actions → Deploy CardForge to GitHub Pages → Run workflow**.
3. The site appears at `https://<owner>.github.io/<repo>/`.

All asset paths are relative, so the site works under a project sub-path or a custom domain
without changes. To deploy from a different branch, edit `on.push.branches` in `pages.yml`.

Preview locally:

```bash
cd web && npm ci && npm run preview   # http://localhost:8000
```

The Pages build is **print-only by design**. Wallet passes need your Apple and Google signing
keys, which must never ship in a public static site. For wallet buttons in the browser, run the
local server instead. It serves the same designer plus the API:

```bash
python3 card-forge/scripts/cardforge.py serve --port 3000
```

| Method & path | Response |
| --- | --- |
| `GET /` | designer (from `web/dist`) |
| `GET /api/templates` | templates + sample payloads |
| `POST /api/generate?format=pdf` | card JSON + optional `perPage, paper, flip, offsetX, offsetY, mode` → `application/pdf` |
| `POST /api/generate?format=pkpass` | `application/vnd.apple.pkpass` (or `application/zip` if unsigned) |
| `POST /api/generate?format=gwallet` | `{ "saveUrl": "https://pay.google.com/gp/v/save/…" }` |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

```bash
(cd web && npm ci && npm run build) && node tests/test_web_parity.mjs
```

## Notes on the spec

Implementing the original spec surfaced a few issues. They are handled and documented here
rather than silently changed:

- **10-up on Letter** leaves 0.75 mm top/bottom margins, and its 2 mm gutter is narrower than
  2 × bleed. The imposition output now carries `warnings`, bleed is clipped at mid-gutter, and
  crop marks that do not fit are omitted. Use 8-up for desktop printers.
- **Crop marks** sit on the sheet perimeter, aligned to each trim line. Marks between cards
  would print over the neighbouring bleed.
- **Cut lines:** perimeter marks end up on the offcuts after the first cut, so the front sheet
  also gets thin dashed lines across the whole page through every trim line. They follow card
  edges and gutters only, never a card face. They are on by default; turn them off with
  `--no-cut-lines` (CLI), `"cutLines": false` (API) or the *Cut lines* checkbox (designer).
- **Apple Wallet:** generic passes show at most 4 auxiliary fields, so `front.fields` beyond 4
  move to `backFields`. Colours are emitted as `rgb()`, and the barcode format follows
  `back.barcode.format` instead of always PDF417.
- **Google Wallet:** the barcode type is mapped (`QR_CODE`, `CODE_128`, `PDF_417`), object ids
  are sanitised, and the generic class is embedded in the JWT.

## License

MIT
