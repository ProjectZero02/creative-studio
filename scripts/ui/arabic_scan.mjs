// Arabic scan: loads each page with the language set to Arabic and lists what
// is still English, plus right-to-left layout problems.
//
//   node scripts/ui/arabic_scan.mjs [base=http://localhost:8110] [routes=/home,/veo] [out=file.json] [shots=dir]
//
// Needs Playwright (any recent version); it drives the installed Microsoft
// Edge (channel "msedge"), so no browser download is needed. In Git Bash set
// MSYS_NO_PATHCONV=1 so "/home" is not rewritten to a Windows path.
//
// Per route it reports:
//   english   visible text, placeholders, aria-labels and titles with English words
//   overflow  horizontal page scroll (px) at 1440 and 390
//   dir       <html dir> after load (must be "rtl")
//   ltrBoxes  inputs/textareas whose text direction is forced LTR
import { createRequire } from "node:module";
import { writeFileSync, mkdirSync } from "node:fs";

const require = createRequire(import.meta.url);
const pw = (() => {
  for (const p of [process.env.PLAYWRIGHT_PATH, "playwright"]) {
    if (!p) continue;
    try { return require(p); } catch (_) { /* try next */ }
  }
  throw new Error("Playwright not found: set PLAYWRIGHT_PATH to its folder");
})();

const args = Object.fromEntries(process.argv.slice(2).map((a) => a.split(/=(.*)/s).slice(0, 2)));
const BASE = args.base || "http://localhost:8110";
const ROUTES = (args.routes ||
  "/home,/nano-banana,/veo,/story,/voice,/lyria,/fashion,/object-rotation,/interior_design,/starter-pack,/library_v2,/brand,/usage,/account,/settings,/projects,/admin/users,/login")
  .split(",").filter(Boolean);
const WIDTHS = (args.widths || "1440,390").split(",").map(Number);

// Names that stay in Latin script in Arabic (common/i18n.py docstring), units
// and file formats.
const ALLOW = new Set(("Nano Banana Gemini Omni Veo Lyria Chirp Vertex AI Google Cloud Imagen TTS HD MP4 MP3 WAV PNG " +
  "JPG JPEG GIF WEBP SVG PDF URL ID API GCS Flash Pro Lite Studio Creative GenMedia OK px fps kbps").split(/\s+/));

function scanScript(allow) {
  const latin = /[A-Za-z]{2,}/g;
  const hasEnglish = (s) => {
    const words = (s.match(latin) || []).filter((w) => !allow.includes(w));
    return words.length > 0;
  };
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && cs.visibility !== "hidden" && cs.display !== "none" && cs.opacity !== "0";
  };
  const out = new Set();
  const walk = (root) => {
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = tw.nextNode())) {
      const s = n.nodeValue.trim().replace(/\s+/g, " ");
      if (!s || !hasEnglish(s)) continue;
      const el = n.parentElement;
      if (!el || !vis(el)) continue;
      if (el.closest("script,style,code,pre,.material-symbols-outlined,.material-icons,mat-icon,.google-symbols,[aria-hidden=true]")) continue;
      if (el.closest("textarea,input")) continue;
      out.add("text: " + s.slice(0, 120));
    }
    for (const el of root.querySelectorAll("[placeholder],[aria-label],[title]")) {
      for (const a of ["placeholder", "aria-label", "title"]) {
        const v = el.getAttribute(a);
        if (v && hasEnglish(v)) out.add(`${a}: ${v.slice(0, 120)}`);
      }
    }
    for (const el of root.querySelectorAll("*")) if (el.shadowRoot) walk(el.shadowRoot);
  };
  walk(document.body);
  const ltrBoxes = [...document.querySelectorAll("textarea,input[type=text],input:not([type])")]
    .filter((el) => vis(el) && getComputedStyle(el).direction === "ltr" && el.getAttribute("dir") !== "auto")
    .map((el) => el.getAttribute("placeholder") || el.getAttribute("aria-label") || el.className.slice(0, 40));
  return {
    dir: document.documentElement.getAttribute("dir"),
    lang: document.documentElement.getAttribute("lang"),
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    english: [...out],
    ltrBoxes,
  };
}

const browser = await pw.chromium.launch({ channel: "msedge" });
const report = {};
for (const width of WIDTHS) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, locale: "ar" });
  await ctx.addCookies([{ name: "gm_lang", value: "ar", url: BASE }]);
  await ctx.addInitScript(() => { try { localStorage.setItem("lang", "ar"); } catch (_) {} });
  const page = await ctx.newPage();
  for (const route of ROUTES) {
    const key = route;
    try {
      await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForSelector(".gm-page, .gm-title, form, main", { timeout: 20000 }).catch(() => {});
      await page.waitForTimeout(2500);
      const r = await page.evaluate(scanScript, [...ALLOW]);
      report[key] ??= {};
      report[key][width] = r;
      if (args.shots) {
        mkdirSync(args.shots, { recursive: true });
        await page.screenshot({ path: `${args.shots}/${route.replace(/\W+/g, "_")}_${width}.png`, fullPage: false });
      }
    } catch (err) {
      report[key] ??= {};
      report[key][width] = { error: String(err).slice(0, 200) };
    }
  }
  await ctx.close();
}
await browser.close();

const summary = Object.entries(report).map(([route, byW]) => {
  const d = byW[WIDTHS[0]] || {};
  const m = byW[WIDTHS[WIDTHS.length - 1]] || {};
  return `${route.padEnd(18)} english=${(d.english || []).length} dir=${d.dir} overflow=${d.overflow}/${m.overflow} ltrBoxes=${(d.ltrBoxes || []).length}${d.error ? " ERROR " + d.error : ""}`;
});
console.log(summary.join("\n"));
if (args.out) writeFileSync(args.out, JSON.stringify(report, null, 2));
