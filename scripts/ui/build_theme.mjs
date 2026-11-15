#!/usr/bin/env node
// Builds assets/ui/studio.css from assets/ui/studio.src.css.
//
// It fills %%FONT_TOKENS%% with every Angular Material "*-font" token that the
// installed Mesop bundle defines, so all Material components use Google Sans.
// Re-run after upgrading Mesop:  node scripts/ui/build_theme.mjs
import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const rel = join("mesop", "web", "src", "app", "prod", "web_package", "styles.css");

function findMesopCss() {
  const candidates = [join(root, ".venv", "Lib", "site-packages", rel)];
  const lib = join(root, ".venv", "lib");
  if (existsSync(lib)) {
    for (const py of readdirSync(lib)) candidates.push(join(lib, py, "site-packages", rel));
  }
  return candidates.find((p) => existsSync(p));
}

const mesopCss = findMesopCss();
if (!mesopCss) {
  console.error("Mesop styles.css not found. Run `uv sync` first.");
  process.exit(1);
}

const tokens = [
  ...new Set(readFileSync(mesopCss, "utf8").match(/--m[a-z]*-[a-z-]*-font(?=:)/g) ?? []),
].sort();

const src = readFileSync(join(root, "assets", "ui", "studio.src.css"), "utf8");
const block = tokens.map((t) => `  ${t}: var(--gm-font);`).join("\n");
const out = src.replace("%%FONT_TOKENS%%", block);
writeFileSync(join(root, "assets", "ui", "studio.css"), out);
console.log(`studio.css written (${tokens.length} font tokens).`);
