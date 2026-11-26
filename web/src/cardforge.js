// CardForge browser engine: imposition math + card/sheet HTML.
// Mirrors card-forge/scripts/impose.py and render.py; tests/test_web_parity.mjs
// checks the imposition output against the Python implementation.
/* global bwipjs */

export const PAPER_SIZES = { letter: [215.9, 279.4], a4: [210.0, 297.0] };
export const GRID_PRESETS = {
  1: [1, 1, { letter: [0, 0], a4: [0, 0] }],
  2: [1, 2, { letter: [0, 12], a4: [0, 15] }],
  4: [2, 2, { letter: [10, 12], a4: [8, 15] }],
  8: [2, 4, { letter: [10, 8], a4: [8, 10] }],
  10: [2, 5, { letter: [10, 2], a4: [8, 4] }],
};
export const CR80_W = 85.6;
export const CR80_H = 53.98;
export const DEFAULT_BLEED = 2.0;
const SAFE_PRINTER_MARGIN = 6.35;

export const TEMPLATES = {
  "auto-insurance": { barcode: "PDF417", badge: "AUTO ID", holder: "Named Insured", id: "Policy Number" },
  "medical-doctor": { barcode: "QR", badge: "HEALTH ID", holder: "Member / Patient", id: "Member ID" },
  "membership-loyalty": { barcode: "CODE128", badge: "MEMBER", holder: "Member", id: "Member ID" },
  "generic-id": { barcode: "QR", badge: "ID", holder: "Name", id: "ID Number" },
};
export const DEFAULT_BRANDING = { primaryColor: "#0F172A", accentColor: "#2563EB", textColor: "#FFFFFF" };

const r3 = (n) => Math.round(n * 1000) / 1000;

export function computeImposition(paper, perPage, flip, offsetX = 0, offsetY = 0, bleed = DEFAULT_BLEED) {
  if (!PAPER_SIZES[paper]) throw new Error(`Unsupported paper: ${paper}`);
  if (!GRID_PRESETS[perPage]) throw new Error(`Unsupported perPage: ${perPage}`);
  if (flip !== "long-edge" && flip !== "short-edge") throw new Error(`Unsupported flip: ${flip}`);
  const [pw, ph] = PAPER_SIZES[paper];
  const [cols, rows, gutters] = GRID_PRESETS[perPage];
  const [gx, gy] = gutters[paper];
  const x0 = (pw - (cols * CR80_W + (cols - 1) * gx)) / 2;
  const y0 = (ph - (rows * CR80_H + (rows - 1) * gy)) / 2;
  const innerX = cols > 1 ? Math.min(bleed, gx / 2) : bleed;
  const innerY = rows > 1 ? Math.min(bleed, gy / 2) : bleed;
  const outerX = Math.max(0, Math.min(bleed, x0));
  const outerY = Math.max(0, Math.min(bleed, y0));

  const warnings = [];
  if (bleed > 0 && cols > 1 && gx < 2 * bleed)
    warnings.push(`Horizontal gutter ${gx}mm < 2 × bleed: bleed clipped to ${innerX}mm between columns.`);
  if (bleed > 0 && rows > 1 && gy < 2 * bleed)
    warnings.push(`Vertical gutter ${gy}mm < 2 × bleed: bleed clipped to ${innerY}mm between rows.`);
  const margin = Math.min(x0, y0);
  if (margin < SAFE_PRINTER_MARGIN)
    warnings.push(`Outer margin is only ${r3(margin)}mm. Most desktop printers will clip the outermost cards; use borderless printing or fewer cards per page.`);
  if (bleed > 0 && margin - bleed < 3)
    warnings.push("Not enough outer margin for 3mm crop marks outside the bleed; crop marks are shortened or omitted.");

  const px = CR80_W + gx, py = CR80_H + gy;
  const slots = [];
  let idx = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const [bc, br] = flip === "long-edge" ? [cols - 1 - c, r] : [c, rows - 1 - r];
      slots.push({
        slotIndex: idx++,
        front: { col: c, row: r, x_mm: r3(x0 + c * px), y_mm: r3(y0 + r * py) },
        back: { col: bc, row: br, x_mm: r3(x0 + bc * px + offsetX), y_mm: r3(y0 + br * py + offsetY) },
      });
    }
  }
  return {
    paper: { name: paper, width_mm: pw, height_mm: ph },
    card: {
      width_mm: CR80_W, height_mm: CR80_H, radius_mm: 3.18, bleed_mm: bleed,
      effectiveBleed_mm: { inner: { x: r3(innerX), y: r3(innerY) }, outer: { x: r3(outerX), y: r3(outerY) } },
    },
    grid: { cols, rows, perPage, gutter_mm: { x: gx, y: gy }, origin_mm: { x: r3(x0), y: r3(y0) }, duplexFlip: flip },
    calibration_mm: { offsetX, offsetY },
    slots,
    warnings,
  };
}

// ------------------------------------------------------------------ validation
const HEX = /^#[0-9A-Fa-f]{6}$/;
export function validate(rec) {
  const errs = [];
  if (!rec || typeof rec !== "object" || Array.isArray(rec)) return ["payload must be an object"];
  for (const k of ["template", "front", "back"]) if (!(k in rec)) errs.push(`'${k}' is required`);
  if (rec.template && !TEMPLATES[rec.template]) errs.push(`template must be one of ${Object.keys(TEMPLATES).join(", ")}`);
  const f = rec.front || {};
  for (const k of ["issuerName", "holderName", "idNumber"]) if (!f[k]) errs.push(`front.${k} is required`);
  if ((f.fields || []).length > 6) errs.push("front.fields: at most 6 items");
  for (const [k, v] of Object.entries(rec.branding || {}))
    if (k.endsWith("Color") && !HEX.test(String(v))) errs.push(`branding.${k} must be #RRGGBB`);
  const bc = (rec.back || {}).barcode;
  if (bc && !["PDF417", "QR", "CODE128"].includes(bc.format)) errs.push("back.barcode.format must be PDF417, QR or CODE128");
  if (bc && !bc.value) errs.push("back.barcode.value is required");
  return errs;
}

export function normalize(rec) {
  const c = structuredClone(rec);
  c.branding = { ...DEFAULT_BRANDING, ...(c.branding || {}) };
  c.back = c.back || {};
  c.front.fields = c.front.fields || [];
  return c;
}

// ------------------------------------------------------------------ CSV
export function parseCSV(text) {
  const rows = [];
  let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') q = false;
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  const [header, ...body] = rows.filter((r) => r.some((c) => c.trim() !== ""));
  if (!header) return [];
  return body.map((r) => {
    const rec = {};
    header.forEach((h, i) => {
      const v = (r[i] ?? "").trim();
      if (v === "") return;
      setPath(rec, h.trim().replace(/^﻿/, ""), /^(true|false)$/i.test(v) ? v.toLowerCase() === "true" : v);
    });
    return prune(rec);
  });
}
function setPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  parts.forEach((p, i) => {
    const last = i === parts.length - 1;
    const key = Array.isArray(cur) ? Number(p) : p;
    if (last) cur[key] = value;
    else {
      if (cur[key] == null) cur[key] = /^\d+$/.test(parts[i + 1]) ? [] : {};
      cur = cur[key];
    }
  });
}
function prune(o) {
  if (Array.isArray(o)) return o.map(prune).filter((v) => v != null && !(typeof v === "object" && Object.keys(v).length === 0));
  if (o && typeof o === "object") {
    const out = {};
    for (const [k, v] of Object.entries(o)) {
      const p = prune(v);
      if (p != null && p !== "" && !(typeof p === "object" && Object.keys(p).length === 0)) out[k] = p;
    }
    return out;
  }
  return o;
}

// ------------------------------------------------------------------ HTML
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (v) => { if (!v) return null; const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v); return m ? `${m[2]}/${m[3]}/${m[1]}` : v; };
const kv = (l, v) => `<div><div class="lbl">${esc(l)}</div><div class="val">${esc(v)}</div></div>`;
const safeUrl = (u) => (typeof u === "string" && /^(data:image\/|https?:|blob:|\.?\/)/i.test(u) ? u : null);
const color = (c, d) => (HEX.test(c || "") ? c : d);

const BWIP = { PDF417: "pdf417", QR: "qrcode", CODE128: "code128" };
export function barcodeSVG(format, value) {
  try {
    if (typeof bwipjs === "undefined") throw new Error("barcode library not loaded");
    const opts = { bcid: BWIP[format], text: value, scale: 2 };
    if (format === "PDF417") Object.assign(opts, { columns: 6, rowmult: 3 });
    if (format === "QR") opts.eclevel = "M";
    if (format === "CODE128") opts.height = 8;
    // Let CSS size the barcode: strip fixed width/height, keep the viewBox.
    return bwipjs.toSVG(opts).replace(/<svg([^>]*?) width="[^"]*" height="[^"]*"/, '<svg$1 preserveAspectRatio="none" shape-rendering="crispEdges"');
  } catch (e) {
    return `<svg viewBox="0 0 100 30" preserveAspectRatio="none"><rect x=".5" y=".5" width="99" height="29" fill="none" stroke="#c00" stroke-dasharray="2 2"/><text x="50" y="17" font-size="5" text-anchor="middle" fill="#c00">${esc(format)}: ${esc(e.message || e)}</text></svg>`;
  }
}

export function frontHTML(card, [bl, bt, , bb]) {
  const b = card.branding, f = card.front, tpl = card.template, T = TEMPLATES[tpl];
  const primary = color(b.primaryColor, DEFAULT_BRANDING.primaryColor);
  const accent = color(b.accentColor, DEFAULT_BRANDING.accentColor);
  const text = color(b.textColor, DEFAULT_BRANDING.textColor);
  const logo = safeUrl(b.logoUrl || b.logoPath), photo = safeUrl(b.photoUrl || b.photoPath);
  const isMember = tpl === "membership-loyalty";
  let badge = T.badge;
  if (isMember) badge = ((f.fields || []).find((x) => x.key === "tier")?.value || badge).toUpperCase();
  const items = (f.fields || []).filter((x) => !(isMember && x.key === "tier")).map((x) => [x.label, x.value]);
  const eff = fmtDate(f.effectiveDate), exp = fmtDate(f.expirationDate);
  if (eff) items.push([isMember ? "Member Since" : "Effective", eff]);
  if (exp) items.push(["Expires", exp]);
  const cols = items.length <= 4 || photo ? 2 : 3;
  return (
    `<div class="f-band" style="height:calc(${bt}mm + 13.4mm);background:${primary}"></div>` +
    `<div class="f-stripe" style="height:calc(${bb}mm + 2.2mm);background:${accent}"></div>` +
    `<div class="trim" style="left:${bl}mm;top:${bt}mm">` +
    `<div class="f-head" style="color:${text}">` +
    (logo ? `<img class="logo" src="${esc(logo)}" alt="">` : "") +
    `<div class="f-issuer"><div class="name">${esc(f.issuerName)}</div>` +
    (f.subtitle ? `<div class="sub">${esc(f.subtitle)}</div>` : "") +
    `</div><div class="badge" style="background:${accent};color:${text}">${esc(badge)}</div></div>` +
    `<div class="f-body"><div class="f-main">` +
    `<div class="f-holder">${kv(T.holder, f.holderName)}</div>` +
    `<div class="f-id"><div class="lbl">${T.id}</div><div class="val mono">${esc(f.idNumber)}</div></div>` +
    `<div class="f-grid" style="--cols:${cols}">${items.map(([k, v]) => kv(k, v)).join("")}</div>` +
    `</div>${photo ? `<img class="f-photo" src="${esc(photo)}" alt="">` : ""}</div></div>`
  );
}

export function backHTML(card, [bl, bt]) {
  const back = card.back || {};
  const mag = !!back.showMagStripe;
  const rows = [...(back.contacts || []), ...(back.fields || [])];
  let text = back.header ? `<div class="b-head">${esc(back.header)}</div>` : "";
  text += rows.map((r) => `<div class="b-row"><span class="k">${esc(r.label)}</span><span class="v">${esc(r.value)}</span></div>`).join("");
  if (back.showSignatureStrip) text += '<div class="b-sig"><span>AUTHORIZED SIGNATURE</span></div>';
  if (back.legalNotice) text += `<div class="b-legal">${esc(back.legalNotice)}</div>`;
  const bc = back.barcode;
  let bcHTML = "";
  if (bc && bc.value) {
    const alt = bc.altText ? `<div class="alt mono">${esc(bc.altText)}</div>` : "";
    bcHTML = `<div class="bc ${bc.format === "QR" ? "bc-QR" : "bc-wide"}"><div class="code">${barcodeSVG(bc.format, bc.value)}</div>${alt}</div>`;
  }
  const dir = bc && bc.format === "QR" ? "row" : "column";
  return (
    (mag ? `<div class="b-mag" style="top:calc(${bt}mm + 5.54mm);height:10.28mm"></div>` : "") +
    `<div class="trim" style="left:${bl}mm;top:${bt}mm">` +
    `<div class="b-content" style="top:${mag ? 18 : 3}mm;flex-direction:${dir}"><div class="b-text">${text}</div>${bcHTML}</div></div>`
  );
}

function bleeds(col, row, cols, rows, eff) {
  const { inner, outer } = eff;
  return [
    col === 0 ? outer.x : inner.x,
    row === 0 ? outer.y : inner.y,
    col === cols - 1 ? outer.x : inner.x,
    row === rows - 1 ? outer.y : inner.y,
  ];
}

function slot(x, y, bl4, inner, guides) {
  const [bl, bt, br, bb] = bl4;
  const style = `left:${r3(x - bl)}mm;top:${r3(y - bt)}mm;width:${r3(CR80_W + bl + br)}mm;height:${r3(CR80_H + bt + bb)}mm`;
  return `<div class="bleedbox" style="${style}">${inner}</div>` + (guides ? `<div class="guide" style="left:${x}mm;top:${y}mm"></div>` : "");
}

function cropMarks(imp, which) {
  const { width_mm: pw, height_mm: ph } = imp.paper;
  const eff = imp.card.effectiveBleed_mm.outer, gap = 1, lw = 0.1;
  const xs = new Set(), ys = new Set();
  for (const s of imp.slots) {
    const p = s[which];
    xs.add(p.x_mm); xs.add(r3(p.x_mm + CR80_W));
    ys.add(p.y_mm); ys.add(r3(p.y_mm + CR80_H));
  }
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const out = [];
  for (const x of [...xs].sort((a, b) => a - b))
    for (const [a, z] of [[Math.max(0, minY - eff.y - gap - 3), minY - eff.y - gap], [maxY + eff.y + gap, Math.min(ph, maxY + eff.y + gap + 3)]])
      if (z - a >= 1) out.push(`<div class="crop" style="left:${r3(x - lw / 2)}mm;top:${r3(a)}mm;width:${lw}mm;height:${r3(z - a)}mm"></div>`);
  for (const y of [...ys].sort((a, b) => a - b))
    for (const [a, z] of [[Math.max(0, minX - eff.x - gap - 3), minX - eff.x - gap], [maxX + eff.x + gap, Math.min(pw, maxX + eff.x + gap + 3)]])
      if (z - a >= 1) out.push(`<div class="crop" style="left:${r3(a)}mm;top:${r3(y - lw / 2)}mm;width:${r3(z - a)}mm;height:${lw}mm"></div>`);
  return out.join("");
}

/** Returns an array of {side: "front"|"back", html} sheets (fronts on odd pages, backs on even). */
export function buildSheets(cards, imp, { mode = "batch", cropMarks: crops = true, guides = false } = {}) {
  const { perPage, cols, rows } = imp.grid;
  const eff = imp.card.effectiveBleed_mm;
  const pages = mode === "copies" ? [Array(perPage).fill(cards[0])] : [];
  if (mode !== "copies") for (let i = 0; i < cards.length; i += perPage) pages.push(cards.slice(i, i + perPage));
  const sheets = [];
  for (const batch of pages) {
    let fr = "", bk = "";
    batch.forEach((card, i) => {
      const s = imp.slots[i];
      const fb = bleeds(s.front.col, s.front.row, cols, rows, eff);
      const bb = bleeds(s.back.col, s.back.row, cols, rows, eff);
      fr += slot(s.front.x_mm, s.front.y_mm, fb, frontHTML(card, fb), guides);
      bk += slot(s.back.x_mm, s.back.y_mm, bb, backHTML(card, bb), guides);
    });
    sheets.push({ side: "front", html: fr + (crops ? cropMarks(imp, "front") : "") });
    sheets.push({ side: "back", html: bk + (crops ? cropMarks(imp, "back") : "") });
  }
  return sheets;
}

/** Single card preview (no bleed) for the on-screen designer. */
export function cardFaces(card) {
  const z = [0, 0, 0, 0];
  return { front: frontHTML(card, z), back: backHTML(card, z) };
}
