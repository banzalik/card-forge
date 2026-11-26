#!/usr/bin/env node
// Convert a CardForge HTML sheet to PDF with headless Chromium (Playwright).
// Usage: node scripts/html2pdf.mjs in.html out.pdf
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const [, , input, output] = process.argv;
if (!input || !output) {
  console.error("usage: html2pdf.mjs <in.html> <out.pdf>");
  process.exit(64);
}
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  console.error("playwright is not installed (npm i -g playwright)");
  process.exit(69);
}
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}
);
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: "load" });
  await page.pdf({ path: output, preferCSSPageSize: true, printBackground: true });
} finally {
  await browser.close();
}
