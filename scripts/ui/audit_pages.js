// One-pass UI consistency audit for every page (docs/UI_CONSISTENCY_AUDIT.md).
//
// Paste into the browser console (or run through a browser tool) on any page
// of a local server. It loads each route in hidden same-origin iframes at
// 1440 and 390 px, waits for Mesop to render, and reports per page:
// sibling buttons that differ in size/radius/kind, controls with a bright
// border, side-by-side cards of different heights, and horizontal scroll.
// No server restarts and no screenshots needed; screenshot only what it flags.
(async () => {
  const ROUTES = ["/home", "/nano-banana", "/veo", "/story", "/voice", "/lyria", "/fashion",
    "/object-rotation", "/interior_design", "/starter-pack", "/library_v2"];
  const WIDTHS = [1440, 390];
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function measure(doc, win) {
    const vis = (el) => { const r = el.getBoundingClientRect(); const cs = win.getComputedStyle(el);
      return r.width > 2 && r.height > 2 && cs.visibility !== "hidden" && cs.display !== "none" &&
        !el.closest(".gm-sr-only,.mat-drawer,.gm-add-pop,.gm-topbar"); };
    const kind = (b) => { const c = String(b.className);
      return c.includes("outlined") ? "tonal" : c.includes("unelevated") ? "filled" : c.includes("raised") ? "raised"
        : c.includes("icon-button") ? "icon" : c.includes("mat-mdc-button") ? "text" : c.includes("toggle") ? "toggle" : "native"; };
    const txt = (el) => (el.innerText || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 24);
    const info = [...doc.querySelectorAll("button")].filter(vis).map((b) => { const r = b.getBoundingClientRect();
      return { t: txt(b), k: kind(b), h: Math.round(r.height), w: Math.round(r.width), x: r.left, y: r.top,
        rad: win.getComputedStyle(b).borderTopLeftRadius }; });
    const siblings = [];
    for (const a of info) for (const b of info) {
      if (a === b || a.x >= b.x || a.k === "icon" || b.k === "icon" || a.k === "toggle") continue;
      const gap = b.x - (a.x + a.w);
      if (Math.abs(a.y + a.h / 2 - (b.y + b.h / 2)) < 12 && gap >= 0 && gap < 40 && a.k === b.k &&
          (Math.abs(a.h - b.h) > 1 || Math.abs(a.w - b.w) > 6 || a.rad !== b.rad))
        siblings.push(`${a.t} ${a.w}x${a.h} | ${b.t} ${b.w}x${b.h}`);
    }
    const heights = [...new Set(info.filter((i) => i.k !== "icon" && i.k !== "native").map((i) => i.h))];
    const outlines = [];
    for (const el of doc.querySelectorAll("button, .mat-button-toggle-group, .mdc-notched-outline__leading")) {
      if (!vis(el)) continue; const cs = win.getComputedStyle(el);
      if (!parseFloat(cs.borderTopWidth)) continue;
      const m = cs.borderTopColor.match(/[\d.]+/g); const alpha = m && m[3] !== undefined ? +m[3] : 1;
      if (alpha >= 0.3) outlines.push(`${txt(el.closest("button,mat-form-field,mat-button-toggle-group") || el)} ${cs.borderTopColor}`);
    }
    const cards = [...doc.querySelectorAll(".gm-demo-pair > * > .gm-demo-card, .gm-demo-pair .gm-demo-card")].filter(vis);
    const cardRows = [];
    for (const a of cards) for (const b of cards) { const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      if (ra.left < rb.left && Math.abs(ra.top - rb.top) < 4 && Math.abs(ra.height - rb.height) > 3)
        cardRows.push(`${Math.round(ra.height)} vs ${Math.round(rb.height)}`); }
    const page = doc.querySelector(".gm-page");
    return { buttonHeights: heights, siblings: [...new Set(siblings)], brightOutlines: [...new Set(outlines)],
      cardHeights: cardRows, hscroll: !!page && page.scrollWidth > page.clientWidth + 1 };
  }

  const out = {};
  for (const route of ROUTES) for (const w of WIDTHS) {
    const f = document.createElement("iframe");
    f.style.cssText = `position:fixed;left:-${w + 50}px;top:0;width:${w}px;height:900px;border:0`;
    f.src = route; document.body.appendChild(f);
    await new Promise((r) => (f.onload = r));
    for (let i = 0; i < 20 && !f.contentDocument.querySelector(".gm-page button, .gm-frame"); i++) await wait(250);
    await wait(1200);
    out[`${route} @${w}`] = measure(f.contentDocument, f.contentWindow);
    f.remove();
  }
  // Only report what needs a look.
  return Object.fromEntries(Object.entries(out).map(([k, v]) => [k, Object.fromEntries(
    Object.entries(v).filter(([n, x]) => (Array.isArray(x) ? (n === "buttonHeights" ? x.length > 1 : x.length) : x)))])
    .filter(([, v]) => Object.keys(v).length));
})();
