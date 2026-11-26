// Assemble the static site into web/dist for GitHub Pages (no bundler needed).
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const skill = join(here, "..", "card-forge");
const dist = join(here, "dist");

rmSync(dist, { recursive: true, force: true });
mkdirSync(join(dist, "vendor"), { recursive: true });

for (const f of readdirSync(join(here, "src"))) cpSync(join(here, "src", f), join(dist, f));
cpSync(join(skill, "assets", "card.css"), join(dist, "card.css"));
cpSync(join(skill, "assets", "schema.json"), join(dist, "schema.json"));
cpSync(join(skill, "assets", "samples"), join(dist, "samples"), { recursive: true });

const bwip = join(here, "node_modules", "bwip-js");
if (!existsSync(bwip)) {
  console.error("bwip-js missing: run `npm ci` (or `npm install`) in web/ first");
  process.exit(1);
}
cpSync(join(bwip, "dist", "bwip-js-min.js"), join(dist, "vendor", "bwip-js-min.js"));
cpSync(join(bwip, "LICENSE"), join(dist, "vendor", "bwip-js.LICENSE.txt"));

// Link back to the repository when built in GitHub Actions.
const repo = process.env.GITHUB_REPOSITORY;
if (repo) {
  const index = join(dist, "index.html");
  const meta = `<meta name="cardforge-repo" content="https://github.com/${repo}">`;
  writeFileSync(index, readFileSync(index, "utf8").replace("</title>", `</title>\n  ${meta}`));
}
writeFileSync(join(dist, ".nojekyll"), "");
console.log(`built ${dist}`);
