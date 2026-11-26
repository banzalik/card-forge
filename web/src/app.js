import {
  computeImposition, buildSheets, cardFaces, validate, normalize, parseCSV, CR80_W, CR80_H, DEFAULT_BLEED,
} from "./cardforge.js";

const $ = (id) => document.getElementById(id);
const STORE = "cardforge.v1";
const state = { records: [], index: 0, api: false };

// ------------------------------------------------------------------ settings
const settingIds = ["paper", "perPage", "mode", "flip", "offsetX", "offsetY", "bleed", "crops", "guides"];
function settings() {
  return {
    paper: $("paper").value,
    perPage: Number($("perPage").value),
    mode: $("mode").value,
    flip: $("flip").value,
    offsetX: Number($("offsetX").value) || 0,
    offsetY: Number($("offsetY").value) || 0,
    bleed: $("bleed").checked,
    crops: $("crops").checked,
    guides: $("guides").checked,
  };
}
function save() {
  try {
    localStorage.setItem(STORE, JSON.stringify({ json: $("json").value, settings: settings(), sample: $("sample").value }));
  } catch { /* storage full or disabled */ }
}
function restore() {
  try {
    const s = JSON.parse(localStorage.getItem(STORE) || "null");
    if (!s) return false;
    $("json").value = s.json || "";
    $("sample").value = s.sample || "auto-insurance";
    for (const id of settingIds) {
      const el = $(id), v = s.settings?.[id];
      if (v === undefined) continue;
      if (el.type === "checkbox") el.checked = !!v; else el.value = String(v);
    }
    return true;
  } catch { return false; }
}

// ------------------------------------------------------------------ data
async function loadSample(name) {
  const res = await fetch(`samples/${name}.json`);
  if (!res.ok) throw new Error(`Could not load sample ${name}`);
  $("json").value = JSON.stringify(await res.json(), null, 2);
  state.index = 0;
  update();
}

function parseInput() {
  const text = $("json").value.trim();
  if (!text) return { records: [], errors: ["Paste card JSON or load a sample."] };
  let data;
  try { data = JSON.parse(text); } catch (e) { return { records: [], errors: [`JSON syntax error: ${e.message}`] }; }
  if (data && Array.isArray(data.cards)) data = data.cards;
  const list = Array.isArray(data) ? data : [data];
  const errors = [];
  const records = [];
  list.forEach((r, i) => {
    const errs = validate(r);
    if (errs.length) errors.push(`Card ${i + 1}${r?.front?.idNumber ? ` (${r.front.idNumber})` : ""}: ${errs.join("; ")}`);
    else records.push(normalize(r));
  });
  return { records, errors };
}

// ------------------------------------------------------------------ render
function sheetElement(imp, html, side) {
  const el = document.createElement("section");
  el.className = `sheet ${side}`;
  el.style.setProperty("--pw", `${imp.paper.width_mm}mm`);
  el.style.setProperty("--ph", `${imp.paper.height_mm}mm`);
  el.innerHTML = html;
  return el;
}

function currentImposition() {
  const s = settings();
  return computeImposition(s.paper, s.perPage, s.flip, s.offsetX, s.offsetY, s.bleed ? DEFAULT_BLEED : 0);
}

function update() {
  const { records, errors } = parseInput();
  state.records = records;
  $("errors").textContent = errors.join("\n");
  if (state.index >= records.length) state.index = 0;

  const nav = $("record-nav");
  nav.hidden = records.length < 2;
  $("record-label").textContent = `Card ${state.index + 1} of ${records.length}`;

  const card = records[state.index];
  if (card) {
    const faces = cardFaces(card);
    $("front").innerHTML = faces.front;
    $("back").innerHTML = faces.back;
  }

  const s = settings();
  const imp = currentImposition();
  $("warnings").innerHTML = imp.warnings.map((w) => `<li>${w.replace(/[<>&]/g, "")}</li>`).join("");
  const sheets = records.length ? buildSheets(records, imp, { mode: s.mode, cropMarks: s.crops, guides: s.guides }) : [];
  const wrap = $("sheets");
  wrap.replaceChildren();
  sheets.forEach((sh, i) => {
    const box = document.createElement("div");
    box.className = "sheet-wrap";
    box.append(`Page ${i + 1} · ${sh.side === "front" ? "Fronts" : "Backs (mirrored for duplex)"}`);
    box.append(sheetElement(imp, sh.html, sh.side));
    wrap.append(box);
  });
  $("sheet-count").textContent = sheets.length ? `(${sheets.length} pages, ${sheets.length / 2} duplex sheet${sheets.length > 2 ? "s" : ""})` : "";
  state.sheets = sheets;
  state.imp = imp;
  save();
}

// ------------------------------------------------------------------ print
function printSheets(sheets, imp) {
  $("page-style").textContent = `@page { size: ${imp.paper.width_mm}mm ${imp.paper.height_mm}mm; margin: 0; }`;
  const root = $("print-root");
  root.replaceChildren(...sheets.map((sh) => sheetElement(imp, sh.html, sh.side)));
  // Give barcodes/images a frame to lay out before opening the print dialog.
  requestAnimationFrame(() => setTimeout(() => window.print(), 50));
}

function calibrationSheets(imp) {
  const flip = imp.grid.duplexFlip;
  const page = (which) => {
    let h = "";
    for (const s of imp.slots) {
      const p = s[which];
      h += `<div class="cal-cross" style="left:${p.x_mm + CR80_W / 2}mm;top:${p.y_mm + CR80_H / 2}mm"></div>`;
      h += `<div class="guide" style="left:${p.x_mm}mm;top:${p.y_mm}mm;border-color:#999"></div>`;
    }
    const mx = imp.paper.width_mm / 2, my = imp.paper.height_mm / 2;
    for (let i = -30; i <= 30; i++) {
      const ln = i % 10 === 0 ? 3 : i % 5 === 0 ? 2 : 1;
      h += `<div class="tick" style="left:${mx + i}mm;top:${my - ln}mm;width:.1mm;height:${ln}mm"></div>`;
      h += `<div class="tick" style="left:${mx - ln}mm;top:${my + i}mm;height:.1mm;width:${ln}mm"></div>`;
      if (i % 10 === 0 && i) {
        h += `<div class="ruler" style="left:${mx + i - 1}mm;top:${my - 5.5}mm">${i}</div>`;
        h += `<div class="ruler" style="left:${mx - 7}mm;top:${my + i - 0.8}mm">${i}</div>`;
      }
    }
    let note = `<b>CardForge duplex calibration — ${which === "front" ? "page 1 (front)" : "page 2 (back)"}</b><br>` +
      `Paper ${imp.paper.name} · ${imp.grid.perPage} per page · flip ${flip} · current offset X ${imp.calibration_mm.offsetX}mm, Y ${imp.calibration_mm.offsetY}mm`;
    if (which === "front") {
      note += `<br>Print BOTH pages duplex at 100%, flip on ${flip === "long-edge" ? "long" : "short"} edge. Hold to a light and read where the back crosshair sits relative to the front one. ` +
        (flip === "long-edge" ? "Use offsetX = −dx, offsetY = +dy." : "Use offsetX = +dx, offsetY = −dy.") +
        " (dx: + is right, dy: + is down, both as seen from this side.)";
    }
    h += `<div class="cal-note" style="top:3mm">${note}</div>`;
    return { side: which, html: h };
  };
  return [page("front"), page("back")];
}

// ------------------------------------------------------------------ wallet (only with `cardforge serve`)
async function detectApi() {
  // The wallet API only exists under `cardforge serve`; skip the probe on static hosts like GitHub Pages.
  if (/\.github\.io$/i.test(location.hostname)) { state.api = false; return; }
  try {
    const res = await fetch("api/templates", { headers: { accept: "application/json" } });
    state.api = res.ok && (res.headers.get("content-type") || "").includes("json");
  } catch { state.api = false; }
  $("wallet-live").hidden = !state.api;
  $("wallet-static").hidden = state.api;
}

async function wallet(format) {
  const card = state.records[state.index];
  if (!card) return;
  const out = $("wallet-out");
  out.textContent = "Generating…";
  const res = await fetch(`api/generate?format=${format}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(card),
  });
  if (!res.ok) { out.textContent = `Error: ${await res.text()}`; return; }
  if (format === "gwallet") {
    const data = await res.json();
    out.replaceChildren();
    if (data.saveUrl) {
      const a = Object.assign(document.createElement("a"), { href: data.saveUrl, target: "_blank", rel: "noopener", textContent: "Add to Google Wallet" });
      out.append(a);
    } else out.textContent = "Server has no Google key configured; unsigned claims were returned.";
  } else {
    const blob = await res.blob();
    const signed = res.headers.get("content-type") === "application/vnd.apple.pkpass";
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(blob), download: `${card.front.idNumber}.pkpass${signed ? "" : ".zip"}`,
    });
    a.click();
    out.textContent = signed ? "Pass downloaded. On iPhone, open in Safari to add to Wallet." : "Unsigned inspection bundle downloaded (server has no Apple certificates).";
  }
}

// ------------------------------------------------------------------ events
function download(name, text, type) {
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

let timer;
$("json").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(update, 250); });
settingIds.forEach((id) => $(id).addEventListener("change", update));
$("load-sample").addEventListener("click", () => loadSample($("sample").value).catch((e) => ($("errors").textContent = e.message)));
$("flipper").addEventListener("click", () => $("flipper").classList.toggle("flipped"));
$("flipper").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("flipper").classList.toggle("flipped"); } });
$("prev").addEventListener("click", () => { state.index = (state.index - 1 + state.records.length) % state.records.length; update(); });
$("next").addEventListener("click", () => { state.index = (state.index + 1) % state.records.length; update(); });
$("print").addEventListener("click", () => { update(); if (state.sheets?.length) printSheets(state.sheets, state.imp); });
$("calibrate").addEventListener("click", () => { const imp = currentImposition(); printSheets(calibrationSheets(imp), imp); });
$("download-json").addEventListener("click", () => download("cards.json", $("json").value, "application/json"));
$("pkpass").addEventListener("click", () => wallet("pkpass"));
$("gwallet").addEventListener("click", () => wallet("gwallet"));
$("file").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const text = await file.text();
  if (/\.csv$/i.test(file.name) || file.type === "text/csv") {
    const recs = parseCSV(text);
    $("json").value = JSON.stringify(recs.length === 1 ? recs[0] : recs, null, 2);
  } else $("json").value = text;
  state.index = 0;
  e.target.value = "";
  update();
});

const repo = document.querySelector('meta[name="cardforge-repo"]')?.content;
if (repo) { $("repo-link").href = repo; $("repo-link").hidden = false; }

(async () => {
  if (restore() && $("json").value.trim()) update();
  else await loadSample($("sample").value).catch((e) => ($("errors").textContent = e.message));
  detectApi();
})();
