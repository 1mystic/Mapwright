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
