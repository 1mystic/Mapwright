document.querySelectorAll("pre.code").forEach((pre) => {
  const b = document.createElement("button"); b.textContent = "Copy";
  b.onclick = () => { navigator.clipboard?.writeText(pre.querySelector("code")?.innerText || pre.innerText.replace(/Copy$/, "")); b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1200); };
  pre.append(b);
});
document.querySelectorAll("[data-tabs]").forEach((box) => {
  const btns = box.querySelectorAll(".tabs button"), panes = box.querySelectorAll(".tabpane");
  btns.forEach((b, i) => b.addEventListener("click", () => { btns.forEach((x) => x.classList.toggle("on", x === b)); panes.forEach((p, j) => p.classList.toggle("on", j === i)); }));
});

// landing page: reveal elements as they scroll into view (staggered within a group)
if (document.querySelector(".hero") && document.documentElement.classList.contains("js")) {
  const groups = ["section > .wrap > h2", "section > .wrap > p.sub", ".grid > .card", ".steps3 > .card", ".stats > .card", ".chips > .chip", ".shots > *", ".window", ".tbl", ".problems", ".two > *", "section .cta", ".card.stat"];
  const seen = new Set(), items = [];
  for (const sel of groups) document.querySelectorAll(sel).forEach((n) => { if (!seen.has(n) && !n.closest(".hero")) { seen.add(n); items.push(n); } });
  const idx = new Map();
  for (const n of items) { const k = n.parentElement; const i = idx.get(k) || 0; idx.set(k, i + 1); n.style.setProperty("--d", Math.min(i, 6) * 0.06 + "s"); n.classList.add("rv"); }
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12, rootMargin: "0px 0px -30px 0px" });
    items.forEach((n) => io.observe(n));
  } else items.forEach((n) => n.classList.add("in"));
}

// screenshots: a small expand button (bottom right) opens the image in a modal; close with the X, a click outside, or Esc
(() => {
  const imgs = document.querySelectorAll(".shots img, .window img");
  if (!imgs.length) return;
  const NS = "http://www.w3.org/2000/svg";
  const svg = (d) => { const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "0 0 16 16"); s.setAttribute("width", "16"); s.setAttribute("height", "16"); s.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", "1.4"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); s.append(p); return s; };
  const EXPAND = "M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9", CLOSE = "M3.5 3.5l9 9M12.5 3.5l-9 9";
  let modal, last;
  const close = () => { if (!modal) return; modal.classList.remove("open"); document.body.classList.remove("zoom-lock"); const m = modal; modal = null; setTimeout(() => m.remove(), 180); if (last) last.focus(); };
  const open = (img, caption) => {
    last = document.activeElement;
    modal = document.createElement("div"); modal.className = "zoom"; modal.setAttribute("role", "dialog"); modal.setAttribute("aria-modal", "true"); modal.setAttribute("aria-label", img.alt || "Screenshot");
    const big = document.createElement("img"); big.src = img.currentSrc || img.src; big.alt = img.alt;
    const x = document.createElement("button"); x.className = "zoomclose"; x.type = "button"; x.setAttribute("aria-label", "Close"); x.append(svg(CLOSE)); x.onclick = close;
    const fig = document.createElement("figure"); fig.append(big);
    if (caption) { const c = document.createElement("figcaption"); c.textContent = caption; fig.append(c); }
    modal.append(fig, x);
    modal.addEventListener("click", (e) => { if (e.target === modal || e.target === fig) close(); });
    document.body.append(modal); document.body.classList.add("zoom-lock"); x.focus();
    requestAnimationFrame(() => modal && modal.classList.add("open"));
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); else if (e.key === "Tab" && modal) { e.preventDefault(); modal.querySelector(".zoomclose").focus(); } });
  imgs.forEach((img) => {
    const wrap = document.createElement("span"); wrap.className = "zoomwrap"; img.replaceWith(wrap); wrap.append(img);
    const cap = img.closest("figure")?.querySelector("figcaption")?.textContent || img.alt;
    const b = document.createElement("button"); b.className = "zoombtn"; b.type = "button"; b.title = "Enlarge"; b.setAttribute("aria-label", "Enlarge: " + (img.alt || "screenshot")); b.append(svg(EXPAND));
    b.onclick = (e) => { e.stopPropagation(); open(img, cap); }; img.style.cursor = "zoom-in"; img.onclick = () => open(img, cap);
    wrap.append(b);
  });
})();
