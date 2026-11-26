# Imposition & Duplex Alignment Spec

All coordinates are millimetres from the **top-left corner of the paper**, measured to the
**trim** (finished card) edge. `scripts/impose.py` and `web/src/cardforge.js` implement this
document. `tests/test_web_parity.mjs` checks that the two agree.

## 1. Physical dimensions

| Metric | mm | in | px @ 300 DPI |
| --- | --- | --- | --- |
| CR80 trim width | 85.60 | 3.370 | 1011 |
| CR80 trim height | 53.98 | 2.125 | 638 |
| Corner radius | 3.18 | 0.125 | 38 |
| Bleed (each side) | 2.00 | 0.079 | 24 |
| Bleed box | 89.60 × 57.98 | 3.528 × 2.283 | 1058 × 685 |

CSS renders at 96 px/in, so 300 DPI output is a `3.125×` device scale. The HTML templates use
physical units (`mm`, `pt`), which makes them resolution independent.

## 2. Grid presets

| Cards / page | Cols × Rows | Letter gutter H × V | A4 gutter H × V |
| --- | --- | --- | --- |
| 1 | 1 × 1 | centred | centred |
| 2 | 1 × 2 | 0 × 12.0 | 0 × 15.0 |
| 4 | 2 × 2 | 10.0 × 12.0 | 8.0 × 15.0 |
| 8 | 2 × 4 | 10.0 × 8.0 | 8.0 × 10.0 |
| 10 | 2 × 5 | 10.0 × 2.0 | 8.0 × 4.0 |

### Resulting outer margins (min of X/Y)

| Preset | Letter | A4 | Fits a 6.35 mm (¼") printer margin? |
| --- | --- | --- | --- |
| 8-up | 17.35 mm (X) | 15.40 mm (X) | yes |
| 10-up | **0.75 mm** (Y) | 5.55 mm (Y) | **no**: borderless printing required |

The 10-up gutters (2 mm Letter, 4 mm A4) are also narrower than `2 × bleed` on Letter. Bleed
is therefore **clipped at the middle of the gutter** so neighbouring cards never paint over
each other (see §4). The imposition output reports every one of these conditions in `warnings`.

## 3. Duplex alignment formula

Let `(Wp, Hp)` be the paper size, `(Wc, Hc) = (85.60, 53.98)`, `(C, R)` the columns and rows,
and `(Gx, Gy)` the gutters.

1. **Grid origin (centred):**
   `X0 = (Wp − (C·Wc + (C−1)·Gx)) / 2`, `Y0 = (Hp − (R·Hc + (R−1)·Gy)) / 2`
2. **Front slot `(c, r)`:**
   `x = X0 + c·(Wc + Gx)`, `y = Y0 + r·(Hc + Gy)`
3. **Back slot.** The card printed in front slot `(c, r)` gets its back in:
   - **long-edge flip** (portrait, book-style): `c' = (C−1) − c`, `r' = r`
   - **short-edge flip** (calendar-style): `c' = c`, `r' = (R−1) − r`

   at `x' = X0 + c'·(Wc + Gx) + Δx` and `y' = Y0 + r'·(Hc + Gy) + Δy`.

Because the grid is centred, mirroring the slot index equals mirroring the geometry. For
long-edge, `x' = Wp − x − Wc`; for short-edge, `y' = Hp − y − Hc`. `Δx, Δy` (printer
calibration) apply **only to the back page**.

### Why each card's back is not rotated

With a long-edge flip, the sheet turns about its vertical axis, so a landscape card's back
reads upright. With a short-edge flip, the sheet turns about its horizontal axis. The
printer driver rotates the back page 180° to compensate, and the slot mirror above already
accounts for that. In both cases the back artwork is rendered upright.

## 4. Bleed, crop marks, safe zone

- Each card paints its background into its bleed box. Bleed per side is
  `inner = min(bleed, gutter/2)` toward a neighbour and `outer = min(bleed, X0|Y0)` toward
  the paper edge.
- **Crop marks** are hair-lines (0.1 mm) that are 3 mm long. They start 1 mm outside the outer
  bleed and are drawn only on the sheet perimeter, one per trim line. Marks between cards would
  overprint the neighbouring bleed. A mark shorter than 1 mm (e.g. 10-up Letter) is omitted.
- **Safe zone:** keep text ≥ 3 mm inside the trim. The templates use a 3 mm inset.
- **Magnetic stripe** (back, optional): ISO/IEC 7811 position, 5.54 mm to 15.82 mm from the top
  edge, full width plus bleed.

## 5. Page order

Page 1 holds fronts and page 2 the matching backs, then page 3 fronts, page 4 backs, and so on.
Every `.sheet` has `break-after: page`, so a duplex printer never merges a front with the
wrong back. In `batch` mode a short final page leaves its unused slots blank on **both** sides.

## 6. Calibration procedure

1. `cardforge calibrate --paper letter --flip long-edge --out calibration.pdf` (or use the
   "Calibration sheet" button in the web designer).
2. Print both pages duplex at 100%, flipping on the selected edge.
3. Hold the sheet to a light. On the front side, measure how far the back crosshair sits
   from the front crosshair (`dx` right-positive, `dy` down-positive) using the mm rulers.
4. Set the offsets:

   | Flip | `offsetX` | `offsetY` |
   | --- | --- | --- |
   | long-edge | `−dx` | `+dy` |
   | short-edge | `+dx` | `−dy` |

   The back page is seen mirrored on the axis the sheet was flipped across, which is why one
   sign changes.
5. Print the target again with the offsets to confirm, then reuse them for that printer, paper
   and tray.
