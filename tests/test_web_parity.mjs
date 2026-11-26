// Checks that the browser imposition engine matches scripts/impose.py exactly.
// Run from the repo root: node tests/test_web_parity.mjs
import { execFileSync } from "node:child_process";
import { computeImposition } from "../web/src/cardforge.js";

let failures = 0;
for (const paper of ["letter", "a4"]) {
  for (const n of [1, 2, 4, 8, 10]) {
    for (const flip of ["long-edge", "short-edge"]) {
      const py = JSON.parse(execFileSync("python3", ["card-forge/scripts/impose.py", "--paper", paper, "--per-page", String(n),
        "--flip", flip, "--offset-x", "0.5", "--offset-y", "-1.25"], { stdio: ["ignore", "pipe", "ignore"] }));
      const js = computeImposition(paper, n, flip, 0.5, -1.25);
      const same = JSON.stringify(py.slots) === JSON.stringify(js.slots)
        && JSON.stringify(py.card.effectiveBleed_mm) === JSON.stringify(js.card.effectiveBleed_mm)
        && py.warnings.length === js.warnings.length;
      if (!same) { failures++; console.error(`MISMATCH ${paper} ${n}-up ${flip}`); }
    }
  }
}
if (failures) process.exit(1);
console.log("web/python imposition parity: OK (20 configurations)");
