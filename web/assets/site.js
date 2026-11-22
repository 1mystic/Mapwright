document.querySelectorAll("pre.code").forEach((pre) => {
  const b = document.createElement("button"); b.textContent = "Copy";
  b.onclick = () => { navigator.clipboard?.writeText(pre.querySelector("code")?.innerText || pre.innerText.replace(/Copy$/, "")); b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1200); };
  pre.append(b);
});
document.querySelectorAll("[data-tabs]").forEach((box) => {
  const btns = box.querySelectorAll(".tabs button"), panes = box.querySelectorAll(".tabpane");
  btns.forEach((b, i) => b.addEventListener("click", () => { btns.forEach((x) => x.classList.toggle("on", x === b)); panes.forEach((p, j) => p.classList.toggle("on", j === i)); }));
});
