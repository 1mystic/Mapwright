/* Mapwright UI. No framework, no build step. Talks to the local daemon (live) or reads a recorded
   bundle (demo on the website). Text from the project is inserted with textContent, or escaped
   before it goes into highlighted code; the only markup inserted as-is is the SVG Mermaid returns
   in strict mode with HTML labels off. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ helpers
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const NS = "http://www.w3.org/2000/svg";
  const icon = (name, cls = "i") => { const s = document.createElementNS(NS, "svg"); s.setAttribute("class", cls); const u = document.createElementNS(NS, "use"); u.setAttribute("href", "icons.svg#" + name); s.append(u); return s; };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ago = (ts) => { const d = Math.max(0, Date.now() / 1000 - ts); return d < 60 ? `${Math.floor(d)}s ago` : d < 3600 ? `${Math.floor(d / 60)}m ago` : d < 86400 ? `${Math.floor(d / 3600)}h ago` : new Date(ts * 1000).toLocaleDateString(); };
  const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const base = (p) => p.split("/").pop();
  const short = (id) => (id || "").split(":").pop();
  const store = { get(k, d) { try { const v = localStorage.getItem("mw." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem("mw." + k, JSON.stringify(v)); } catch (e) {} } };
  const url = (path, params = {}) => { const e = Object.entries(params).filter(([, v]) => v != null && v !== "").sort(([a], [b]) => a.localeCompare(b)); return e.length ? path + "?" + e.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&") : path; };
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // ------------------------------------------------------------------ data source
  const params = new URLSearchParams(location.hash.slice(1));
  const lsGet = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
  // Hosted page (not served by the daemon): talk to the user's own daemon on localhost; only a loopback address is accepted.
  const LOCAL_HOST = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  const okBase = (u) => /^http:\/\/(127\.0\.0\.1|localhost):\d{2,5}$/.test(u || "");
  if (okBase(params.get("a"))) lsSet("mw.a", params.get("a"));
  const BASE = LOCAL_HOST ? "" : (okBase(lsGet("mw.a")) ? lsGet("mw.a") : "http://127.0.0.1:7979");
  if (params.get("t") && !LOCAL_HOST) lsSet("mw.live", "1");
  const DEMO = new URLSearchParams(location.search).has("demo") || (document.documentElement.dataset.demo === "1" && !lsGet("mw.live"));
  let token = params.get("t");
  const TOKEN_RE = /^[A-Za-z0-9._~+\-]{8,}$/;
  const tokenStore = {
    load() { for (const st of [() => sessionStorage, () => localStorage]) { try { const v = st().getItem("mw.t"); if (v) return v; } catch (e) {} } return null; },
    save(t) { for (const st of [() => sessionStorage, () => localStorage]) { try { st().setItem("mw.t", t); } catch (e) {} } },
    clear() { for (const st of [() => sessionStorage, () => localStorage]) { try { st().removeItem("mw.t"); } catch (e) {} } },
  };
  if (token) tokenStore.save(token); else token = tokenStore.load();
  if (params.get("t")) history.replaceState(null, "", location.pathname + location.search + (params.get("p") ? "#p=" + params.get("p") : ""));
  let bundle = null;

  async function api(path, body, method) {
    if (DEMO) {
      if (body !== undefined) { toast("warn", "Read-only demo", "Install Mapwright to record steps, todos and settings."); throw new Error("demo"); }
      if (!bundle) bundle = await (await fetch("demo.json")).json();
      if (path in bundle) return JSON.parse(JSON.stringify(bundle[path]));
      const k = Object.keys(bundle).find((x) => x.split("?")[0] === path.split("?")[0] && path.includes("step=live") === x.includes("step=live"));
      if (k && /\/(version|state|settings|projects|integrations|catalog)$/.test(path.split("?")[0])) return bundle[k];
      throw new Error("not in demo");
    }
    let r;
    try { r = await fetch(BASE + path, { method: method || (body !== undefined ? "POST" : "GET"), cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: body !== undefined ? JSON.stringify(body) : undefined }); }
    catch (e) { throw Object.assign(new Error("daemon not reachable"), { network: true }); }
    const data = await r.json().catch(() => ({}));
    if (r.ok && token) tokenStore.save(token);
    if (!r.ok) throw Object.assign(new Error(data.error || String(r.status)), { status: r.status });
    return data;
  }

  // ------------------------------------------------------------------ state
  const FIXED = [
    { id: "system", title: "System", icon: "graph" }, { id: "overview", title: "Overview", icon: "eye" }, { id: "d:architecture", title: "Architecture", icon: "layers" },
    { id: "d:files", title: "Files", icon: "folder" }, { id: "d:classes", title: "Classes", icon: "class" },
    { id: "d:data", title: "Data", icon: "database" }, { id: "d:cloud", title: "Cloud", icon: "cloud" },
    { id: "d:processes", title: "Processes", icon: "route" }, { id: "logic", title: "Logic", icon: "function" },
    { id: "concepts", title: "Concepts", icon: "puzzle" }, { id: "timeline", title: "Timeline", icon: "history" },
  ];
  const DTITLE = { architecture: "Architecture · layers and modules", files: "File organisation", classes: "Classes", data: "Data model",
    cloud: "Cloud & infrastructure", processes: "API & core processes", calls: "Call graph", concepts: "Concept map" };
  const LAYER_COLOR = { interface: "#3574f0", ui: "#2aacb8", service: "#5fb865", core: "#9b8cff", data: "#c77dbb", integration: "#e5a13e", util: "#868a91", config: "#b3ae60", test: "#6f737a" };
  const S = {
    projects: [], key: params.get("p") || store.get("key", null), st: null, model: null, modelFor: null, version: -1,
    step: "live", base: "auto", tabs: store.get("tabs", []), active: /^(system|overview|logic|concepts|timeline|d:[a-z]+)$/.test(params.get("view") || "") ? params.get("view") : store.get("active", "system"), left: store.get("left", "project"),
    leftOpen: store.get("leftOpen", true), rightOpen: store.get("rightOpen", true), bottomOpen: store.get("bottomOpen", true), btab: store.get("btab", "steps"),
    sel: null, settings: null, integ: null, brief: null, expanded: new Set(store.get("expanded", [])), view: {}, fnFilter: "", fnSel: null, conn: "connecting",
  };
  const saveUI = () => { ["tabs", "active", "left", "leftOpen", "rightOpen", "bottomOpen", "btab"].forEach((k) => store.set(k, S[k])); store.set("expanded", [...S.expanded]); store.set("key", S.key); };
  const P = (rest) => `/v1/p/${encodeURIComponent(S.key)}/${rest}`;
  const stepParam = () => (S.step === "live" ? "live" : String(S.step));

  // ------------------------------------------------------------------ theme & mermaid
  function cssv(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function setTheme(t) {
    document.documentElement.dataset.theme = t; store.set("theme", t);
    $("#w-theme").replaceChildren(icon(t === "dark" ? "sun" : "moon"));
    const dark = t === "dark";
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", maxTextSize: 900000, maxEdges: 4000,
      flowchart: { htmlLabels: false, useMaxWidth: false, curve: "basis", padding: 12, nodeSpacing: 34, rankSpacing: 46 },
      class: { htmlLabels: false, useMaxWidth: false }, er: { useMaxWidth: false }, state: { useMaxWidth: false },
      themeVariables: { fontFamily: "Inter, Segoe UI, system-ui, sans-serif", fontSize: "13px", darkMode: dark,
        background: cssv("--editor"), primaryColor: dark ? "#2b2d30" : "#f7f8fa", primaryTextColor: cssv("--text"), primaryBorderColor: dark ? "#4e5157" : "#c9ccd6",
        secondaryColor: dark ? "#26282b" : "#ffffff", tertiaryColor: dark ? "#232427" : "#f2f3f5", lineColor: dark ? "#6f737a" : "#a8adbd",
        clusterBkg: dark ? "rgba(255,255,255,.025)" : "rgba(53,116,240,.03)", clusterBorder: dark ? "#3c3f44" : "#dfe1e5", titleColor: cssv("--text-2"),
        edgeLabelBackground: cssv("--editor"), nodeTextColor: cssv("--text"), mainBkg: dark ? "#2b2d30" : "#f7f8fa", attributeBackgroundColorEven: dark ? "#26282b" : "#fff",
        attributeBackgroundColorOdd: dark ? "#2b2d30" : "#f7f8fa", classText: cssv("--text") } });
    S.view = {}; // re-render diagrams in the new colours
    if (S.st) renderView();
  }

  // ------------------------------------------------------------------ boot & polling
  async function boot() {
    setTheme(["dark", "light"].includes(params.get("theme")) ? params.get("theme") : store.get("theme", "dark"));
    wire();
    if (!DEMO && !token) { S.conn = "token"; renderAll(); authBox("missing"); return; }
    try {
      const pr = await api("/v1/projects");
      S.projects = pr.projects.filter((p) => p.exists);
      if (!S.projects.some((p) => p.key === S.key)) S.key = S.projects[0]?.key || null;
      S.conn = DEMO ? "demo" : "live";
      api("/v1/settings").then((s) => { S.settings = s; if (!store.get("theme", null) && s.settings.theme) setTheme(s.settings.theme); }).catch(() => {});
    } catch (e) { S.conn = e.status === 401 ? "token" : "offline"; renderAll(); if (e.status === 401) authBox("rejected"); else offlineBox(); return; }
    if (!S.key) { renderAll(); welcome(); return; }
    await load(true);
    if (params.get("view") === "settings") settings(); // #view=settings opens the Settings dialog (used by scripts/screenshots.py)
    setInterval(poll, 1500);
  }
  async function poll() {
    if (!S.key || document.hidden) return;
    try {
      const v = await api(P("version"));
      if (S.conn !== "live" && !DEMO) { S.conn = "live"; renderStatus(); }
      if (v.version !== S.version || v.journal !== S.journal) { S.journal = v.journal; await load(false); }
    } catch (e) { if (!DEMO) { if (e.status === 401) { S.conn = "token"; S.st = null; renderAll(); authBox("rejected"); } else { S.conn = "offline"; renderStatus(); } } }
  }
  // ---- first-run / unauthorised / offline states (the token is never written into the DOM)
  function parseToken(text) {
    const raw = String(text || "").trim(); if (!raw) return null;
    let t = null, p = null;
    const h = raw.includes("#") ? raw.slice(raw.indexOf("#") + 1) : raw.includes("t=") ? raw : "";
    if (h) { const q = new URLSearchParams(h); t = q.get("t"); p = q.get("p"); }
    if (!t && !h) t = raw;
    return t && TOKEN_RE.test(t) ? { t, p } : null;
  }
  function forgetToken() { tokenStore.clear(); token = null; S.conn = "token"; S.st = null; S.projects = []; toast("ok", "Token forgotten", "Run `mapwright open` to sign in again."); closeMenus(); renderAll(); authBox("missing"); }
  function stateBox(id, title, paras, cmd) {
    const v = $("#view"); v.replaceChildren();
    const w = el("div", "welcome"), b = el("div", "box"); b.id = id; b.dataset.testid = id;
    const h = el("h1"); const img = el("img"); img.src = "mark.svg"; img.width = 34; img.alt = ""; h.append(img, document.createTextNode(title));
    b.append(h); paras.forEach((t) => b.append(el("p", null, t)));
    if (cmd) { const c = el("div", "cmd"); c.append(el("code", null, cmd)); const cp = el("button", "btn sm", "Copy"); cp.onclick = () => { navigator.clipboard?.writeText(cmd); toast("ok", "Copied", cmd); }; c.append(cp); b.append(c); }
    w.append(b); v.append(w); return b;
  }
  function authBox(why) {
    const b = stateBox("auth-box", "Unauthorised", [why === "rejected" ? "The saved token is not valid any more (the daemon was probably reset)." : "This page needs a local access token, which comes with the link that `mapwright open` prints.",
      "Run this in a terminal to open Mapwright with the right link:"], "mapwright open");
    b.append(el("p", null, "Or paste that link (it ends in #p=…&t=…) or just the token here:"));
    const row = el("div", "actions"); const inp = el("input", "input"); inp.id = "auth-input"; inp.type = "password"; inp.autocomplete = "off"; inp.spellcheck = false; inp.placeholder = "Link or token"; inp.style.flex = "1";
    const go = el("button", "btn primary", "Use token"); go.id = "auth-go";
    const apply = () => { const r = parseToken(inp.value); if (!r) { toast("err", "That does not look like a link or token", "Paste the full link from `mapwright open`."); return; }
      tokenStore.save(r.t); if (r.p) store.set("key", r.p); inp.value = ""; location.hash = ""; location.reload(); };
    go.onclick = apply; inp.onkeydown = (e) => { if (e.key === "Enter") apply(); };
    row.append(inp, go); b.append(row);
    if (token) { const f = el("button", "btn sm", "Forget saved token"); f.id = "auth-forget"; f.onclick = forgetToken; b.append(Object.assign(el("div", "actions"), {})); b.lastChild.append(f); }
    setTimeout(() => inp.focus(), 0);
  }
  function offlineBox() {
    const b = stateBox("offline-box", "Mapwright is not running", ["The local daemon did not answer on this address. Start it in a terminal:"], "mapwright up -d");
    const row = el("div", "actions"); const r = el("button", "btn primary", "Retry"); r.id = "offline-retry"; r.onclick = () => location.reload(); row.append(r); b.append(row);
  }
  async function load(first) {
    const [st, integ] = await Promise.all([api(P("state")), first || !S.integ ? api(url("/v1/integrations", { key: S.key })).catch(() => null) : Promise.resolve(S.integ)]);
    const prevSteps = S.st ? S.st.steps.length : 0;
    S.st = st; S.version = st.version; S.integ = integ; S.model = null; S.brief = null;
    if (!first && st.steps.length > prevSteps) { const s = st.steps[st.steps.length - 1]; toast("ok", `Step ${s.n} recorded`, s.title); }
    if (S.step !== "live" && !st.steps.some((s) => s.n === S.step)) S.step = "live";
    api(url(P("brief"), {})).then((b) => { S.brief = b; renderStatus(); }).catch(() => {});
    if (first && !S.tabs.length) S.tabs = [];
    renderAll();
  }
  async function model() {
    const want = stepParam() + ":" + S.version;
    if (S.model && S.modelFor === want) return S.model;
    S.model = await api(url(P("model"), { step: stepParam() })); S.modelFor = want; return S.model;
  }

  // ------------------------------------------------------------------ rendering: frame
  function renderAll() {
    const ide = $("#ide");
    ide.style.setProperty("--lw", S.leftOpen ? store.get("lw", 280) + "px" : "0px");
    ide.style.setProperty("--rw", S.rightOpen ? store.get("rw", 320) + "px" : "0px");
    $("#left").hidden = !S.leftOpen; $("#right").hidden = !S.rightOpen; $("#bottom").hidden = !S.bottomOpen;
    $("#bottom").style.setProperty("--bh", store.get("bh", 220) + "px");
    renderToolbar(); renderStripes(); renderLeft(); renderTabs(); renderView(); renderRight(); renderBottom(); renderStatus();
  }
  function renderToolbar() {
    const p = S.projects.find((x) => x.key === S.key);
    const gated = !DEMO && (S.conn === "token" || S.conn === "offline") && !S.st;
    for (const id of ["w-project", "w-step", "w-step-add", "w-agents", "w-search"]) { const n = $("#" + id); n.disabled = gated; n.classList.toggle("gated", gated); n.setAttribute("aria-disabled", gated); }
    if (gated) { $("#w-project-name").textContent = "—"; $("#w-project").title = ""; $("#w-step-badge").textContent = "—"; $("#w-step").classList.remove("live"); $("#w-step-name").textContent = ""; $("#w-agents-dot").className = "ldot"; $("#w-agents-txt").textContent = S.conn === "token" ? "signed out" : "offline"; return; }
    $("#w-project-name").textContent = p ? p.name : "No project";
    $("#w-project").title = p ? p.root : "Choose a project";
    const live = S.step === "live", st = S.st;
    $("#w-step").classList.toggle("live", live);
    $("#w-step-badge").textContent = live ? "LIVE" : "STEP " + S.step;
    const s = st && !live ? st.steps.find((x) => x.n === S.step) : null;
    $("#w-step-name").textContent = live ? (st ? `${st.pending.length} change${st.pending.length === 1 ? "" : "s"} since step ${st.steps.length ? st.steps[st.steps.length - 1].n : 0}` : "") : (s ? s.title : "");
    const conn = (S.integ?.targets || []).filter((t) => Object.values(t.scopes || {}).some((x) => x.connected));
    $("#w-agents-dot").className = "ldot " + (conn.length ? "on" : "");
    $("#w-agents-txt").textContent = conn.length ? conn.map((t) => t.title.split(" (")[0]).slice(0, 2).join(", ") + (conn.length > 2 ? ` +${conn.length - 2}` : "") : DEMO ? "demo" : "connect an agent";
  }
  const LEFT = [["project", "folder", "Project"], ["structure", "list", "Structure"], ["concepts", "puzzle", "Mechanisms"], ["setup", "plug", "Connect"]];
  const BOTTOM = [["steps", "history", "Steps"], ["todo", "check-square", "TODO"], ["problems", "warning", "Problems"], ["activity", "activity", "Activity"]];
  function renderStripes() {
    const l = $("#stripe-l"); l.replaceChildren();
    for (const [id, ic, title] of LEFT) {
      const b = el("button", "sbtn" + (S.leftOpen && S.left === id ? " on" : "")); b.title = title; b.append(icon(ic));
      b.onclick = () => { if (id === "setup") { openTab({ id: "setup", title: "Connect an agent", icon: "plug" }); return; } if (S.left === id && S.leftOpen) S.leftOpen = false; else { S.left = id; S.leftOpen = true; } saveUI(); renderAll(); };
      l.append(b);
    }
    l.append(el("div", "grow"));
    for (const [id, ic, title] of BOTTOM) {
      const b = el("button", "sbtn" + (S.bottomOpen && S.btab === id ? " on" : "")); b.title = title; b.append(icon(ic));
      const n = id === "problems" ? (S.st?.problems.length || 0) : id === "todo" ? (S.st?.todos.filter((t) => t.status === "open").length || 0) : 0;
      if (n && id === "problems") b.append(el("span", "dot"));
      b.onclick = () => { if (S.btab === id && S.bottomOpen) S.bottomOpen = false; else { S.btab = id; S.bottomOpen = true; } saveUI(); renderAll(); };
      l.append(b);
    }
    const r = $("#stripe-r"); r.replaceChildren();
    for (const [id, ic, title] of [["inspector", "info", "Inspector"], ["brief", "doc", "Agent brief"]]) {
      const b = el("button", "sbtn" + (S.rightOpen && (S.rightMode || "inspector") === id ? " on" : "")); b.title = title; b.append(icon(ic));
      b.onclick = () => { if ((S.rightMode || "inspector") === id && S.rightOpen) S.rightOpen = false; else { S.rightMode = id; S.rightOpen = true; } saveUI(); renderAll(); };
      r.append(b);
    }
  }

  // ------------------------------------------------------------------ left panel
  function fileIcon(path, dir) {
    if (dir) { const s = el("span", "ficon dir"); s.append(icon("folder")); return s; }
    const ext = (path.split(".").pop() || "").toLowerCase(), name = base(path);
    const map = { py: ["py", "PY"], js: ["js", "JS"], jsx: ["js", "JSX"], mjs: ["js", "JS"], ts: ["ts", "TS"], tsx: ["ts", "TSX"], sql: ["sql", "SQL"], prisma: ["prisma", "PR"],
      md: ["md", "MD"], json: ["json", "{}"], yaml: ["yaml", "Y"], yml: ["yml", "Y"], toml: ["toml", "T"], css: ["css", "#"], html: ["html", "<>"], tf: ["tf", "TF"] };
    const [cls, txt] = /dockerfile|compose/i.test(name) ? ["docker", "D"] : map[ext] || ["other", ext.slice(0, 2).toUpperCase() || "·"];
    return el("span", "ficon " + cls, txt);
  }
  function renderLeft() {
    const body = $("#left-body"), tools = $("#left-tools"); body.replaceChildren(); tools.replaceChildren();
    const title = LEFT.find((x) => x[0] === S.left)?.[2] || "Project"; $("#left-title").textContent = title;
    if (!S.st) { body.append(el("div", "empty", "No project yet.")); return; }
    if (S.left === "project") projectTree(body, tools);
    else if (S.left === "structure") structurePanel(body);
    else if (S.left === "concepts") conceptList(body);
  }
  function projectTree(body, tools) {
    const collapse = el("button", "tbtn"); collapse.title = "Collapse all"; collapse.append(icon("minus")); collapse.onclick = () => { S.expanded.clear(); saveUI(); renderLeft(); };
    const changed = el("button", "tbtn" + (S.onlyChanged ? " on" : "")); changed.title = "Only changed files"; changed.append(icon("diff")); changed.onclick = () => { S.onlyChanged = !S.onlyChanged; renderLeft(); };
    tools.append(changed, collapse);
    const f = el("div", "filter"); f.append(icon("search")); const inp = el("input"); inp.placeholder = "Filter files"; inp.value = S.treeFilter || ""; f.append(inp); body.append(f);
    inp.oninput = debounce(() => { S.treeFilter = inp.value; drawTree(); }, 120);
    const tree = el("div", "tree"); body.append(tree);
    const drawTree = () => {
      tree.replaceChildren();
      const q = (S.treeFilter || "").toLowerCase();
      let files = S.st.files;
      if (S.onlyChanged) files = files.filter((x) => x.status);
      if (q) files = files.filter((x) => x.path.toLowerCase().includes(q));
      const root = {};
      for (const fl of files) { let cur = root; const parts = fl.path.split("/"); parts.slice(0, -1).forEach((p) => { cur = cur[p + "/"] = cur[p + "/"] || {}; }); cur[parts[parts.length - 1]] = fl; }
      const walk = (node, depth, prefix) => {
        const dirs = Object.keys(node).filter((k) => k.endsWith("/")).sort(), leaves = Object.keys(node).filter((k) => !k.endsWith("/")).sort();
        for (const d of dirs) {
          const full = prefix + d, open = q || S.onlyChanged || S.expanded.has(full);
          const r = el("div", "row"); r.style.paddingLeft = 6 + depth * 14 + "px";
          const tw = el("span", "tw"); tw.append(icon(open ? "chevron-down" : "chevron-right")); r.append(tw, fileIcon(d, true), el("span", "nm", d.slice(0, -1)));
          const ch = countChanged(node[d]); if (ch) r.append(el("span", "meta", `${ch} changed`));
          r.onclick = () => { open ? S.expanded.delete(full) : S.expanded.add(full); saveUI(); drawTree(); };
          tree.append(r);
          if (open) walk(node[d], depth + 1, full);
        }
        for (const lf of leaves) {
          const fl = node[lf];
          const r = el("div", "row" + (fl.status ? " " + fl.status : "") + (fl.secret ? " secret" : "") + (S.sel?.kind === "file" && S.sel.ref === fl.path ? " sel" : ""));
          r.style.paddingLeft = 6 + depth * 14 + 12 + "px"; r.title = fl.path + (fl.secret ? " (secret-looking: never read)" : "");
          r.append(fileIcon(fl.path), el("span", "nm", lf));
          if (fl.status) r.append(el("span", "meta", { A: "added", M: "modified", D: "deleted" }[fl.status]));
          else if (fl.functions) r.append(el("span", "meta", `${fl.functions} fn`));
          r.onclick = () => select({ kind: "file", ref: fl.path, file: fl.path });
          r.ondblclick = () => fl.status !== "D" && !fl.secret && openFile(fl.path);
          tree.append(r);
        }
      };
      walk(root, 0, "");
      if (!files.length) tree.append(el("div", "empty", S.onlyChanged ? "No changes since the last step." : "No files match."));
    };
    drawTree();
  }
  function countChanged(node) { let n = 0; for (const [k, v] of Object.entries(node)) n += k.endsWith("/") ? countChanged(v) : v.status ? 1 : 0; return n; }
  async function structurePanel(body) {
    const path = S.sel?.file || (S.active.startsWith("file:") ? S.active.slice(5) : null);
    if (!path) { body.append(el("div", "empty", "Select a file in the Project panel or a node in a diagram to see its classes and functions.")); return; }
    body.append(el("div", "section", base(path)));
    try {
      const f = await api(url(P("file"), { path, step: stepParam() }));
      const list = el("div", "tree");
      for (const s of (f.symbols || []).sort((a, b) => a.line - b.line)) {
        const r = el("div", "row"); r.style.paddingLeft = (s.kind === "function" && s.qual.includes(".") ? 22 : 8) + "px";
        r.append(icon(s.kind === "class" ? "class" : "function"), el("span", "nm", s.qual.split(".").pop()), el("span", "meta", s.kind === "function" ? `cx ${s.complexity} · ${s.line}` : String(s.line)));
        r.onclick = () => s.fid ? select({ kind: "function", ref: s.fid, file: path, line: s.line }) : openFile(path, s.line);
        r.ondblclick = () => s.fid ? openFlow(s.fid) : openFile(path, s.line);
        list.append(r);
      }
      if (!f.symbols?.length) list.append(el("div", "empty", "No classes or functions in this file."));
      body.append(list);
    } catch (e) { body.append(el("div", "empty", "Not available for this file.")); }
  }
  function conceptList(body) {
    const list = el("div", "tree");
    for (const c of S.st.concepts) {
      const r = el("div", "row"); r.append(icon(c.icon), el("span", "nm", c.title));
      const cl = c.claims.length ? c.claims.every((x) => x.status === "verified") ? "claimed ✓" : "claimed ?" : "";
      r.append(el("span", "meta", cl || `${c.evidence.length}`));
      r.onclick = () => { select({ kind: "concept", ref: c.id }); openTab(FIXED.find((t) => t.id === "concepts")); };
      list.append(r);
    }
    if (!S.st.concepts.length) list.append(el("div", "empty", "No mechanisms detected yet. They appear as code that uses caching, queues, auth, retries and so on is written."));
    body.append(list);
  }

  // ------------------------------------------------------------------ tabs
  function allTabs() { return [...FIXED, ...S.tabs]; }
  function openTab(t) { if (!t) return; if (!FIXED.some((x) => x.id === t.id) && !S.tabs.some((x) => x.id === t.id)) S.tabs.push(t); S.active = t.id; saveUI(); renderTabs(); renderView(); renderStatus(); if (S.left === "structure") renderLeft(); }
  function closeTab(id) { S.tabs = S.tabs.filter((t) => t.id !== id); if (S.active === id) S.active = S.tabs.length ? S.tabs[S.tabs.length - 1].id : "overview"; delete S.view[id]; saveUI(); renderTabs(); renderView(); }
  function renderTabs() {
    const box = $("#tabs"); box.replaceChildren();
    for (const t of allTabs()) {
      const fixed = FIXED.some((x) => x.id === t.id);
      const tab = el("div", "tab" + (S.active === t.id ? " on" : "")); tab.setAttribute("role", "tab"); tab.title = t.hint || t.title;
      tab.append(t.file ? fileIcon(t.file) : icon(t.icon || "file"), el("span", null, t.title));
      if (!fixed) { const x = el("span", "x"); x.append(icon("close")); x.onclick = (e) => { e.stopPropagation(); closeTab(t.id); }; tab.append(x); }
      tab.onclick = () => { S.active = t.id; saveUI(); renderTabs(); renderView(); renderStatus(); };
      tab.onauxclick = (e) => { if (e.button === 1 && !fixed) closeTab(t.id); };
      box.append(tab);
    }
    box.querySelector(".tab.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  const openFile = (path, line) => { openTab({ id: "file:" + path, title: base(path), file: path, hint: path }); if (line) { S.view["file:" + path] = { line }; renderView(); } };
  const openFlow = (fid) => openTab({ id: "flow:" + fid, title: short(fid) + "()", icon: "function", hint: "Flowchart of " + fid });
  const openDiff = (path, from, to) => openTab({ id: `diff:${path}|${from}|${to}`, title: base(path), icon: "diff", hint: `${path}: step ${from} → ${to}` });

  // ------------------------------------------------------------------ views
  function renderView() {
    const v = $("#view");
    if (!S.st) return;
    const id = S.active;
    v.replaceChildren();
    if (id === "overview") overview(v);
    else if (id.startsWith("d:")) diagramView(v, id.slice(2));
    else if (id === "logic") logicView(v);
    else if (id === "concepts") conceptsView(v);
    else if (id === "system") systemView(v);
    else if (id === "timeline") timelineView(v);
    else if (id === "setup") setupView(v);
    else if (id.startsWith("file:")) fileView(v, id.slice(5));
    else if (id.startsWith("flow:")) flowView(v, id.slice(5));
    else if (id.startsWith("diff:")) { const [path, from, to] = id.slice(5).split("|"); diffView(v, path, from, to); }
    else { S.active = "overview"; overview(v); }
  }
  function welcome(msg) {
    const v = $("#view"); v.replaceChildren();
    const w = el("div", "welcome"), b = el("div", "box");
    const h = el("h1"); const img = el("img"); img.src = "mark.svg"; img.width = 34; h.append(img, document.createTextNode("Welcome to Mapwright"));
    b.append(h, el("p", null, msg || "A live map of what your coding agent is building: structure, architecture, data, cloud, logic and every step it takes."));
    if (!msg || S.conn === "live") {
      const row = el("div", "actions"); const inp = el("input", "input"); inp.placeholder = "/path/to/your/project"; inp.style.flex = "1";
      const go = el("button", "btn primary", "Track folder"); go.onclick = async () => { try { const r = await api("/v1/projects", { root: inp.value.trim() }); S.key = r.key; saveUI(); location.reload(); } catch (e) { toast("err", "Could not track that folder", e.message); } };
      row.append(inp, go); b.append(row, el("p", null, "Or run `mapwright init` inside the project. Then connect your agent from the Connect panel."));
    }
    w.append(b); v.append(w);
  }

  // ---- system view: an abstract, icon-based picture of the whole system, built from the analysis
  const SYS_NODE = { w: 184, h: 84, gx: 64, gy: 22, top: 56, left: 28 };
  async function buildSystem() {
    const m = await model(), st = S.st, files = st.files || [];
    const byLayer = {}; for (const mod of Object.values(m.modules || {})) (byLayer[mod.layer] = byLayer[mod.layer] || []).push(mod.file);
    const status = (paths) => { const set = new Set(paths); let a = 0, c = 0; for (const f of files) if (set.has(f.path)) { if (f.status === "A") a++; else if (f.status === "M") c++; } return a ? "new" : c ? "changed" : null; };
    const fileRows = (paths) => [...new Set(paths)].sort().map((p) => ({ label: base(p), meta: p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "", run: () => openFile(p) }));
    const fnRows = (paths) => { const set = new Set(paths); return Object.entries(m.functions || {}).filter(([, f]) => set.has(f.file)).sort((a, b) => (b[1].complexity || 0) - (a[1].complexity || 0)).slice(0, 12).map(([id, f]) => ({ label: f.qual, meta: `cx ${f.complexity || 0}`, run: () => select({ kind: "function", ref: id, file: f.file, line: f.line }) })); };
    const infra = (st.infra && st.infra.nodes) || [];
    const infraRows = (nodes) => nodes.map((n) => ({ label: n.label, meta: n.kind, run: () => select({ kind: "infra", ref: n.id }) }));
    const comps = [];
    const add = (c) => { c.sections = c.sections || []; c.stats = c.stats || []; c.state = c.state || status(c.files || []); comps.push(c); };
    const routes = m.routes || [], pages = routes.filter((r) => r.method === "PAGE"), api = routes.filter((r) => r.method !== "PAGE");
    const routeRows = (rs) => rs.slice(0, 40).map((r) => ({ label: `${r.method} ${r.path}`, meta: r.handler || "", run: () => (r.fid ? select({ kind: "function", ref: r.fid, file: r.file, line: r.line }) : r.file && openFile(r.file, r.line)) }));
    add({ id: "clients", tier: 0, icon: "user", title: "Users & clients", sub: pages.length ? `${pages.length} pages` : "browsers · apps · agents", desc: "Whoever or whatever calls the system: people in a browser, other services, agents.",
      files: [], stats: [["pages", pages.length], ["API routes", api.length]], sections: [{ title: "Pages", rows: routeRows(pages) }] });
    const ui = byLayer.ui || [], itf = byLayer.interface || [];
    if (ui.length || pages.length) add({ id: "ui", tier: 1, icon: "eye", title: "User interface", sub: `${ui.length} modules`, desc: "Screens and components the user sees.", files: ui,
      stats: [["modules", ui.length], ["functions", fnRows(ui).length ? Object.values(m.functions || {}).filter((f) => ui.includes(f.file)).length : 0]], sections: [{ title: "Modules", rows: fileRows(ui) }, { title: "Most complex", rows: fnRows(ui) }] });
    if (itf.length || api.length) add({ id: "api", tier: 1, icon: "route", title: "API & interface", sub: api.length ? `${api.length} routes` : `${itf.length} modules`, desc: "Entry points: HTTP routes, CLI commands, handlers.", files: itf,
      stats: [["routes", api.length], ["modules", itf.length]], sections: [{ title: "Routes", rows: routeRows(api) }, { title: "Modules", rows: fileRows(itf) }, { title: "Most complex", rows: fnRows(itf) }] });
    const svc = byLayer.service || [], core = byLayer.core || [];
    if (svc.length) add({ id: "services", tier: 2, icon: "box", title: "Services", sub: `${svc.length} modules`, desc: "Business logic: what the system actually does.", files: svc,
      stats: [["modules", svc.length]], sections: [{ title: "Modules", rows: fileRows(svc) }, { title: "Most complex", rows: fnRows(svc) }] });
    if (core.length) add({ id: "core", tier: 2, icon: "function", title: "Core logic", sub: `${core.length} modules`, desc: "Shared domain code used by the other layers.", files: core,
      stats: [["modules", core.length]], sections: [{ title: "Modules", rows: fileRows(core) }, { title: "Most complex", rows: fnRows(core) }] });
    const tables = Object.entries(m.tables || {}), dbNodes = infra.filter((n) => n.kind === "db");
    const dfiles = [...(byLayer.data || []), ...tables.map(([, t]) => t.file).filter(Boolean)];
    if (tables.length || dbNodes.length || (byLayer.data || []).length) add({ id: "db", tier: 3, icon: "database", title: "Database", sub: tables.length ? `${tables.length} tables` : dbNodes[0]?.label || "data layer", desc: "Where data is stored: tables, collections and their access rules.", files: dfiles,
      stats: [["tables", tables.length], ["engines", dbNodes.length]], sections: [{ title: "Engines", rows: infraRows(dbNodes) }, { title: "Tables and collections", rows: tables.map(([k, t]) => ({ label: t.name || k, meta: t.kind || t.source || "", run: () => select({ kind: "table", ref: k, file: t.file, line: t.line }) })) }, { title: "Data code", rows: fileRows(byLayer.data || []) }] });
    for (const [kind, id, ic, title, d] of [["cache", "cache", "bolt", "Cache", "Fast temporary storage in front of slower data."], ["queue", "queue", "radio", "Queue & jobs", "Work handed off to run later or elsewhere."], ["search", "search", "search", "Search", "Full-text or vector search index."]]) {
      const ns = infra.filter((n) => n.kind === kind); if (ns.length) add({ id, tier: 3, icon: ic, title, sub: ns.map((n) => n.label).join(", "), desc: d, files: [], stats: [["nodes", ns.length]], sections: [{ title: "Found in", rows: infraRows(ns) }] });
    }
    const intg = byLayer.integration || [], ext = infra.filter((n) => n.kind === "external" || n.kind === "cloud");
    if (intg.length) add({ id: "integrations", tier: 4, icon: "plug", title: "Integrations", sub: `${intg.length} modules`, desc: "Code that talks to outside services.", files: intg, stats: [["modules", intg.length]], sections: [{ title: "Modules", rows: fileRows(intg) }, { title: "Most complex", rows: fnRows(intg) }] });
    for (const n of ext.slice(0, 8)) add({ id: "x:" + n.id, tier: 4, icon: n.kind === "cloud" ? "cloud" : "globe", title: n.label, sub: n.kind === "cloud" ? "cloud platform" : "external service", desc: n.detail || "An outside service the system depends on.", files: n.sources || [], stats: [["kind", n.kind]], sections: [{ title: "Seen in", rows: fileRows((n.sources || []).filter((s) => files.some((f) => f.path === s))) }] });
    if (ext.length > 8) add({ id: "x:more", tier: 4, icon: "globe", title: `+${ext.length - 8} more`, sub: "external services", desc: "More outside services.", files: [], stats: [["count", ext.length - 8]], sections: [{ title: "Services", rows: infraRows(ext.slice(8)) }] });
    const plat = infra.filter((n) => !["db", "cache", "queue", "search", "external", "cloud", "app"].includes(n.kind));
    for (const [kinds, id, ic, title, d] of [[["container"], "containers", "server", "Containers", "How the system is packaged and run."], [["ci"], "ci", "rotate", "CI / CD", "Automated build, test and deploy."], [["cdn", "function", "hosting"], "hosting", "cloud", "Hosting & functions", "Where it is deployed."]]) {
      const ns = plat.filter((n) => kinds.includes(n.kind)); if (ns.length) add({ id, tier: 5, icon: ic, title, sub: ns.length + (ns.length === 1 ? " item" : " items"), desc: d, files: ns.flatMap((n) => n.sources || []), stats: [["items", ns.length]], sections: [{ title: "Found in", rows: infraRows(ns) }] });
    }
    const tests = byLayer.test || []; if (tests.length) add({ id: "tests", tier: 5, icon: "beaker", title: "Tests", sub: `${tests.length} files`, desc: "Automated checks.", files: tests, stats: [["files", tests.length]], sections: [{ title: "Files", rows: fileRows(tests) }] });
    return comps;
  }
  async function systemView(v) {
    const sc = el("div", "scroll sys"); v.append(sc);
    let comps; try { comps = await buildSystem(); } catch (e) { sc.append(el("div", "empty", "The system picture is not available for this step.")); return; }
    if (S.active !== "system") return;
    S.sysComps = Object.fromEntries(comps.map((c) => [c.id, c]));
    const { w, h, gx, gy, top, left } = SYS_NODE, main = [0, 1, 2, 3, 4].filter((t) => comps.some((c) => c.tier === t));
    const TIER = ["Clients", "Interface", "Logic", "Data", "Outside"];
    const col = Object.fromEntries(main.map((t, i) => [t, i])), pos = {};
    let maxRows = 1; for (const t of main) { const cs = comps.filter((c) => c.tier === t); maxRows = Math.max(maxRows, cs.length); cs.forEach((c, i) => { pos[c.id] = { x: left + col[t] * (w + gx), y: top + i * (h + gy), c }; }); }
    const plat = comps.filter((c) => c.tier === 5), W = Math.max(main.length * (w + gx) - gx + left * 2, plat.length * (w + 20) + left * 2, 480);
    const platY = top + maxRows * (h + gy) + 44;
    plat.forEach((c, i) => { pos[c.id] = { x: left + i * (w + 20), y: platY, c }; });
    const H = plat.length ? platY + h + 28 : top + maxRows * (h + gy) + 10;
    const svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "sysmap"); svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const mk = (tag, attrs, parent = svg) => { const n = document.createElementNS(NS, tag); for (const [k, val] of Object.entries(attrs || {})) n.setAttribute(k, val); parent.append(n); return n; };
    const defs = mk("defs"), mark = mk("marker", { id: "sysarrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs); mk("path", { d: "M0 1 L9 5 L0 9z", class: "sysarrowhead" }, mark);
    main.forEach((t, i) => { const lb = mk("text", { x: left + i * (w + gx), y: 30, class: "systier" }); lb.textContent = TIER[t].toUpperCase(); });
    if (plat.length) { const lb = mk("text", { x: left, y: platY - 16, class: "systier" }); lb.textContent = "PLATFORM"; mk("line", { x1: left, x2: W - left, y1: platY - 30, y2: platY - 30, class: "sysrule" }); }
    const link = (a, b) => { const p = pos[a], q = pos[b], x1 = p.x + w, y1 = p.y + h / 2, x2 = q.x, y2 = q.y + h / 2, mx = (x1 + x2) / 2; mk("path", { d: `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2 - 2} ${y2}`, class: "sysedge", "marker-end": "url(#sysarrow)" }); };
    for (let i = 0; i < main.length - 1; i++) {
      const A = comps.filter((c) => c.tier === main[i]), B = comps.filter((c) => c.tier === main[i + 1]);
      if (A.length * B.length <= 12) for (const a of A) for (const b of B) link(a.id, b.id);
      else { A.forEach((a, k) => link(a.id, B[Math.min(k, B.length - 1)].id)); B.forEach((b, k) => k >= A.length && link(A[A.length - 1].id, b.id)); }
    }
    for (const p of Object.values(pos)) {
      const c = p.c, g = mk("g", { class: "sysnode" + (S.sel?.kind === "component" && S.sel.ref === c.id ? " on" : ""), transform: `translate(${p.x},${p.y})`, tabindex: 0, role: "button" });
      mk("title", {}, g).textContent = c.desc;
      mk("rect", { width: w, height: h, rx: 10, class: "sysbox" }, g);
      mk("circle", { cx: 30, cy: h / 2, r: 18, class: "sysdisc" }, g);
      const ic = mk("use", { href: "icons.svg#" + c.icon, x: 20, y: h / 2 - 10, width: 20, height: 20, class: "sysicon" }, g);
      const t1 = mk("text", { x: 58, y: h / 2 - 3, class: "systitle" }, g); t1.textContent = c.title.length > 17 ? c.title.slice(0, 16) + "…" : c.title;
      const t2 = mk("text", { x: 58, y: h / 2 + 15, class: "syssub" }, g); t2.textContent = (c.sub || "").length > 22 ? c.sub.slice(0, 21) + "…" : c.sub || "";
      if (c.state) { mk("circle", { cx: w - 12, cy: 12, r: 5, class: "sysdot " + c.state }, g); mk("title", {}, g).textContent = c.state === "new" ? "new since the last step" : "changed since the last step"; }
      const open = () => { select({ kind: "component", ref: c.id }); svg.querySelectorAll(".sysnode.on").forEach((n) => n.classList.remove("on")); g.classList.add("on"); };
      g.addEventListener("click", open); g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    }
    sc.append(svg, el("div", "syshint", "Click a component to see what is inside it. Drawn from the code: layers, routes, tables and infrastructure."));
  }

  // ---- overview
  function overview(v) {
    const st = S.st, sc = el("div", "scroll"); v.append(sc);
    const hero = el("div", "hero"); const t = el("div"); t.append(el("h1", null, st.name), el("div", "path mono", st.root)); hero.append(t, el("div", "grow"));
    const brief = el("button", "btn"); brief.append(icon("doc"), document.createTextNode("Agent brief")); brief.onclick = () => { S.rightMode = "brief"; S.rightOpen = true; renderAll(); };
    const rec = el("button", "btn primary"); rec.append(icon("flag"), document.createTextNode("Record step")); rec.onclick = recordStep;
    hero.append(brief, rec); sc.append(hero);
    const c = st.counts, stats = el("div", "stats");
    for (const [k, label, tab] of [["files", "files", "d:files"], ["modules", "modules", "d:architecture"], ["functions", "functions", "logic"], ["classes", "classes", "d:classes"],
      ["tables", "tables", "d:data"], ["routes", "routes", "d:processes"], ["concepts", "mechanisms", "concepts"], ["infra", "infra nodes", "d:cloud"]]) {
      const s = el("div", "stat"); s.append(el("b", null, String(c[k])), el("span", null, label)); s.onclick = () => openTab(FIXED.find((x) => x.id === tab)); stats.append(s);
    }
    sc.append(stats);
    const grid = el("div", "grid2"); sc.append(grid);
    // latest step
    const last = st.steps[st.steps.length - 1];
    const c1 = card("What the agent did", "timeline");
    if (st.pending.length) {
      c1.body.append(el("div", "li", null)); c1.body.lastChild.append(el("span", "badge auto", "IN PROGRESS"), el("span", "nm", `${st.pending.length} file change${st.pending.length === 1 ? "" : "s"} since step ${last ? last.n : 0}`));
      c1.body.append(changeList(st.pending.slice(0, 6), last ? String(last.n) : "live", "live"));
    }
    if (last) {
      const li = el("div", "li"); li.append(el("span", "badge " + last.source, last.source.toUpperCase()), el("span", "nm", `${last.n}. ${last.title}`), el("span", "meta", ago(last.ts)));
      li.onclick = () => { setStep(last.n); openTab(FIXED.find((x) => x.id === "timeline")); }; c1.body.append(li);
      c1.body.append(deltaChips(last.summary));
      if (last.title_check && last.title_check !== "ok") c1.body.append(Object.assign(el("div", "chip warn", "⚠ " + last.title_check), { style: "margin-top:8px;white-space:normal;height:auto;padding:4px 8px" }));
    }
    grid.append(c1.card);
    // layers
    const c2 = card("Layers", "d:architecture"); const total = Object.values(st.layers).reduce((a, b) => a + b, 0) || 1;
    const bar = el("div", "layerbar"), keys = el("div", "lkeys");
    for (const [k, n] of Object.entries(st.layers).sort((a, b) => b[1] - a[1])) { const i = el("i"); i.style.width = (100 * n / total) + "%"; i.style.background = LAYER_COLOR[k] || "#888"; i.title = `${k}: ${n}`; bar.append(i); const s = el("span"); const d = el("i"); d.style.background = LAYER_COLOR[k] || "#888"; s.append(d, document.createTextNode(`${k} ${n}`)); keys.append(s); }
    c2.body.append(bar, keys); grid.append(c2.card);
    // mechanisms
    const c3 = card("Mechanisms in use", "concepts"); const cw = el("div", "concepts");
    for (const cc of st.concepts.slice(0, 18)) { const p = el("span", "cpill"); p.append(icon(cc.icon), document.createTextNode(cc.title)); p.onclick = () => { select({ kind: "concept", ref: cc.id }); openTab(FIXED.find((x) => x.id === "concepts")); }; cw.append(p); }
    if (!st.concepts.length) cw.append(el("span", "empty", "None detected yet."));
    c3.body.append(cw); grid.append(c3.card);
    // routes
    if (st.routes.length) { const c4 = card("Entry points", "d:processes"); const l = el("div", "list"); for (const r of st.routes.slice(0, 8)) { const li = el("div", "li"); li.append(el("span", "badge acc", r.method), el("span", "nm mono", r.path), el("span", "meta", short(r.fid || r.handler || ""))); li.onclick = () => r.fid ? select({ kind: "function", ref: r.fid, file: r.file, line: r.line }) : openFile(r.file, r.line); l.append(li); } c4.body.append(l); grid.append(c4.card); }
    // infra
    const c5 = card("Cloud & infrastructure", "d:cloud"); const l5 = el("div", "list");
    for (const n of st.infra.nodes.slice(0, 8)) { const li = el("div", "li"); li.append(icon({ db: "database", cache: "layers", queue: "inbox", storage: "box", external: "globe", ci: "git-merge", cloud: "cloud", function: "bolt", app: "server", container: "box", cdn: "globe", search: "search" }[n.kind] || "server"), el("span", "nm", n.label), el("span", "meta", n.kind)); li.onclick = () => select({ kind: "infra", ref: n.id }); l5.append(li); }
    if (!st.infra.nodes.length) l5.append(el("div", "empty", "No Dockerfile, compose, Terraform, CI or service SDKs found yet."));
    c5.body.append(l5); grid.append(c5.card);
    // hotspots & algorithms
    const c6 = card("Complexity hotspots", "logic"); const l6 = el("div", "list");
    for (const h of st.hotspots.slice(0, 7)) { const li = el("div", "li"); li.append(cxBadge(h.complexity), el("span", "nm mono", short(h.id) + "()"), el("span", "meta", base(h.file))); li.onclick = () => select({ kind: "function", ref: h.id, file: h.file, line: h.line }); li.ondblclick = () => openFlow(h.id); l6.append(li); }
    c6.body.append(l6); grid.append(c6.card);
    if (st.algorithms.length) { const c7 = card("Algorithms & techniques (hints)", "logic"); const l7 = el("div", "list"); for (const a of st.algorithms.slice(0, 7)) { const li = el("div", "li"); li.append(el("span", "nm mono", short(a.id) + "()"), el("span", "meta", a.hints.filter((x) => x !== "async I/O").slice(0, 2).join(", "))); li.onclick = () => select({ kind: "function", ref: a.id, file: a.file, line: a.line }); li.ondblclick = () => openFlow(a.id); l7.append(li); } c7.body.append(l7); grid.append(c7.card); }
    // todos & verification
    const c8 = card("Plan", null); const open = st.todos.filter((t) => t.status === "open"), done = st.todos.filter((t) => t.status === "done");
    const l8 = el("div", "list"); for (const td of [...open, ...done].slice(0, 7)) { const li = el("div", "li"); li.append(icon(td.status === "done" ? "check-square" : "check"), el("span", "nm", td.text), el("span", "meta", td.status === "done" ? (td.verified ? "verified" : "unverified") : td.id)); li.onclick = () => { S.btab = "todo"; S.bottomOpen = true; renderAll(); }; l8.append(li); }
    if (!st.todos.length) l8.append(el("div", "empty", "The agent has not recorded a plan. It can with the `todo` tool."));
    c8.body.append(l8); grid.append(c8.card);
    const c9 = card("Verification", null);
    const bad = st.problems.filter((x) => x.kind !== "parse");
    c9.body.append(el("div", "li", null)); c9.body.lastChild.append(icon(bad.length ? "warning" : "check"), el("span", "nm", bad.length ? `${bad.length} claim(s) do not check out` : "Everything the agent claimed checks out against the code"));
    for (const x of bad.slice(0, 4)) { const li = el("div", "li"); li.append(el("span", "badge " + x.status, x.status), el("span", "nm", x.text)); li.onclick = () => { S.btab = "problems"; S.bottomOpen = true; renderAll(); }; c9.body.append(li); }
    grid.append(c9.card);
  }
  function card(title, tab) {
    const c = el("div", "card"), h = el("h3"); h.append(el("span", null, title), el("span", "grow"));
    if (tab) { const a = el("a", null, "Open →"); a.href = "#"; a.onclick = (e) => { e.preventDefault(); openTab(FIXED.find((x) => x.id === tab)); }; h.append(a); }
    const body = el("div"); c.append(h, body); return { card: c, body };
  }
  function cxBadge(n) { return el("span", "cx" + (n >= 20 ? " vh" : n >= 10 ? " h" : ""), String(n)); }
  function deltaChips(sm) {
    const w = el("div", "chips"); w.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;margin-top:8px";
    w.append(el("span", "chip", `${sm.files} files`), el("span", "chip new", `+${sm.added}`), el("span", "chip removed", `−${sm.removed}`));
    for (const [k, d] of Object.entries(sm.delta || {})) for (const [s, n] of Object.entries(d)) w.append(el("span", "chip " + s, `${n} ${s} ${k.replace(/s$/, "")}${n > 1 ? "s" : ""}`));
    return w;
  }
  function changeList(changes, from, to) {
    const box = el("div", "files"); box.style.marginTop = "6px";
    for (const ch of changes) {
      const r = el("div", "fchg"); r.append(el("span", "k " + ch.kind, ch.kind[0].toUpperCase()), el("span", "p mono", ch.path));
      const c = el("span", "c"); if ("added" in ch) { c.append(el("span", "a", `+${ch.added}`), document.createTextNode(" "), el("span", "r", `−${ch.removed}`)); } else c.textContent = ch.note ? "not read" : "";
      r.append(c); r.style.cursor = "pointer"; r.onclick = (e) => { e.stopPropagation(); if (!ch.note) openDiff(ch.path, from, to); };
      box.append(r);
    }
    return box;
  }

  // ---- diagrams
  function vbar(title) { const b = el("div", "vbar"); b.append(el("span", "title", title)); return b; }
  function stepSelect(onchange) {
    const s = el("select", "select"); s.title = "Highlight what changed compared with";
    const opts = [["auto", "vs previous step"], ["none", "no highlighting"], ...S.st.steps.map((x) => [String(x.n), `vs step ${x.n}: ${x.title.slice(0, 40)}`])];
    for (const [v, t] of opts) { const o = el("option", null, t); o.value = v; s.append(o); }
    s.value = S.base; s.onchange = () => { S.base = s.value; onchange(); }; return s;
  }
  async function diagramView(v, kind, focus) {
    const bar = vbar(DTITLE[kind] || kind); v.append(bar);
    const tabId = S.active; const vs = S.view[tabId] = S.view[tabId] || { k: 1, x: 20, y: 20, src: false, focus: focus || null };
    if (kind === "processes" || kind === "calls") {
      const sel = el("select", "select"); sel.title = kind === "processes" ? "One entry point" : "Centre on a function";
      sel.append(Object.assign(el("option", null, kind === "processes" ? "all entry points" : "most connected functions"), { value: "" }));
      if (kind === "processes") for (const r of S.st.routes) { const o = el("option", null, `${r.method} ${r.path}`); o.value = `${r.method} ${r.path}`; sel.append(o); }
      else model().then((m) => { Object.entries(m.functions).filter(([, f]) => f.callers.length + f.callees.length).sort((a, b) => a[0].localeCompare(b[0])).slice(0, 400).forEach(([fid]) => { const o = el("option", null, short(fid) + "()"); o.value = fid; sel.append(o); }); sel.value = vs.focus || ""; });
      sel.value = vs.focus || ""; sel.onchange = () => { vs.focus = sel.value || null; vs.fit = true; renderView(); };
      bar.append(sel);
    }
    if (kind === "processes") { const cg = el("button", "btn sm", "Call graph"); cg.onclick = () => openTab({ id: "d:calls", title: "Call graph", icon: "graph" }); bar.append(cg); }
    if (["architecture", "classes", "data", "calls", "files"].includes(kind)) bar.append(stepSelect(() => { vs.fit = true; renderView(); }));
    const note = el("span", "note"); bar.append(note, el("span", "spacer"));
    const legend = el("span", "legend"); bar.append(legend);
    const canvas = el("div", "canvas"); v.append(canvas);
    const z = zoomControls(bar, canvas, vs);
    const src = el("button", "tbtn" + (vs.src ? " on" : "")); src.title = "Show the Mermaid source"; src.append(icon("code"));
    src.onclick = () => { vs.src = !vs.src; renderView(); };
    const copy = el("button", "tbtn"); copy.title = "Copy Mermaid"; copy.append(icon("copy"));
    const dl = el("button", "tbtn"); dl.title = "Download SVG"; dl.append(icon("download"));
    bar.append(el("span", "sep"), src, copy, dl);
    canvas.append(el("div", "msg", "Drawing…"));
    let d;
    try { d = await api(url(P("diagram/" + kind), { step: stepParam(), base: S.base === "auto" ? null : S.base, focus: vs.focus })); }
    catch (e) { canvas.replaceChildren(el("div", "msg", "This view is not available here.")); return; }
    if (S.active !== tabId) return;
    note.textContent = d.note || "";
    for (const [k, dd] of Object.entries(d.delta || {})) for (const [s, n] of Object.entries(dd)) legend.append(el("span", "chip " + s, `${n} ${s}`));
    copy.onclick = () => { navigator.clipboard?.writeText(d.mermaid); toast("ok", "Copied", "Mermaid source is on the clipboard."); };
    await drawMermaid(canvas, d, vs, z, (key, info) => onNode(info), (key, info) => openNode(info));
    dl.onclick = () => { const svg = canvas.querySelector("svg"); if (!svg) return; const blob = new Blob([svg.outerHTML], { type: "image/svg+xml" }); const a = el("a"); a.href = URL.createObjectURL(blob); a.download = `${S.st.name}-${kind}.svg`; a.click(); };
  }
  let mcount = 0;
  async function drawMermaid(canvas, d, vs, z, onClick, onOpen) {
    if (vs.src) { canvas.replaceChildren(el("pre", "src", d.mermaid)); return; }
    let svg;
    try { svg = (await mermaid.render("mw" + ++mcount, d.mermaid)).svg; }
    catch (e) { document.getElementById("dmw" + mcount)?.remove(); canvas.replaceChildren(el("div", "msg", "This diagram could not be drawn; the Mermaid source is shown instead."), el("pre", "src", d.mermaid)); return; }
    const stage = el("div", "stage"); stage.innerHTML = svg; canvas.replaceChildren(stage);   // Mermaid output, strict mode
    const s = stage.querySelector("svg"); if (!s) return;
    const w = s.viewBox.baseVal?.width || s.getBBox().width, h = s.viewBox.baseVal?.height || s.getBBox().height;
    s.setAttribute("width", w); s.setAttribute("height", h); s.style.maxWidth = "none";
    if (vs.fit !== false || !vs.fitted) { z.fit(w, h); vs.fitted = true; vs.fit = false; } else z.apply();
    const nodes = d.nodes || {};
    const keyOf = (g) => { const id = g.id || ""; let m;
      if ((m = id.match(/^flowchart-(.+)-\d+$/))) return m[1];
      if ((m = id.match(/^classId-(.+)-\d+$/))) return "class:" + m[1];
      if ((m = id.match(/^entity-(.+)-\d+$/))) return "entity:" + m[1];
      return null; };
    stage.querySelectorAll("g.node, g[id^=classId-], g[id^=entity-]").forEach((g) => {
      const key = keyOf(g); const info = key && nodes[key]; if (!info) return;
      g.style.cursor = "pointer"; g.setAttribute("tabindex", "0");
      const t = document.createElementNS(NS, "title"); t.textContent = (info.ref || "") + (info.file ? `\n${info.file}${info.line ? ":" + info.line : ""}` : "") + "\nclick: inspect · double-click: open"; g.prepend(t);
      g.addEventListener("click", (e) => { e.stopPropagation(); stage.querySelectorAll(".picked").forEach((x) => x.classList.remove("picked")); g.classList.add("picked"); onClick(key, info); });
      g.addEventListener("dblclick", (e) => { e.stopPropagation(); onOpen(key, info); });
      g.addEventListener("keydown", (e) => { if (e.key === "Enter") onOpen(key, info); });
    });
  }
  function zoomControls(bar, canvas, vs) {
    const lbl = el("span", "zoomlbl"); const apply = () => { const st = canvas.querySelector(".stage"); if (st) st.style.transform = `translate(${vs.x}px,${vs.y}px) scale(${vs.k})`; lbl.textContent = Math.round(vs.k * 100) + "%"; };
    const zoomAt = (f, cx, cy) => { const k2 = Math.min(4, Math.max(0.08, vs.k * f)); vs.x = cx - (cx - vs.x) * (k2 / vs.k); vs.y = cy - (cy - vs.y) * (k2 / vs.k); vs.k = k2; apply(); };
    const fit = (w, h) => { const r = canvas.getBoundingClientRect(); const pad = 28; if (!w) { const s = canvas.querySelector("svg"); if (!s) return; w = +s.getAttribute("width"); h = +s.getAttribute("height"); }
      vs.k = Math.min(1.25, Math.max(0.08, Math.min((r.width - pad * 2) / w, (r.height - pad * 2) / h))); vs.x = (r.width - w * vs.k) / 2; vs.y = Math.max(pad, (r.height - h * vs.k) / 2); apply(); };
    const b = (ic, title, fn) => { const x = el("button", "tbtn"); x.title = title; x.append(icon(ic)); x.onclick = fn; return x; };
    bar.append(b("zoom-out", "Zoom out", () => { const r = canvas.getBoundingClientRect(); zoomAt(1 / 1.2, r.width / 2, r.height / 2); }), lbl,
      b("zoom-in", "Zoom in", () => { const r = canvas.getBoundingClientRect(); zoomAt(1.2, r.width / 2, r.height / 2); }), b("fit", "Fit to window", () => fit()));
    canvas.addEventListener("wheel", (e) => { e.preventDefault(); const r = canvas.getBoundingClientRect(); if (e.ctrlKey || e.metaKey || !e.shiftKey) zoomAt(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top); else { vs.x -= e.deltaY; apply(); } }, { passive: false });
    let drag = null;
    canvas.addEventListener("pointerdown", (e) => { if (e.button !== 0 || e.target.closest("pre")) return; drag = { x: e.clientX, y: e.clientY, ox: vs.x, oy: vs.y, moved: false }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener("pointermove", (e) => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; canvas.classList.add("drag"); } vs.x = drag.ox + dx; vs.y = drag.oy + dy; apply(); });
    canvas.addEventListener("pointerup", () => { drag = null; canvas.classList.remove("drag"); });
    return { apply, fit };
  }
  function onNode(info) {
    const m = { module: "module", function: "function", class: "class", table: "table", file: "file", infra: "infra", concept: "concept", route: "route", dir: "dir", package: "package", layer: "layer" };
    select({ kind: m[info.kind] || info.kind, ref: info.ref, file: info.file, line: info.line });
  }
  function openNode(info) {
    if (info.kind === "function") openFlow(info.ref);
    else if (info.kind === "concept") { select({ kind: "concept", ref: info.ref }); openTab(FIXED.find((x) => x.id === "concepts")); }
    else if (info.kind === "dir") { S.left = "project"; S.leftOpen = true; S.expanded.add(info.ref + "/"); saveUI(); renderLeft(); }
    else if (info.file && !info.file.includes(" ")) openFile(info.file, info.line);
  }

  // ---- logic
  async function logicView(v) {
    const sp = el("div", "split"), side = el("div", "side"), content = el("div", "content"); sp.append(side, content); v.append(sp);
    const f = el("div", "filter"); f.append(icon("search")); const inp = el("input"); inp.placeholder = "Filter functions"; inp.value = S.fnFilter; f.append(inp);
    const sort = el("select", "select"); sort.style.margin = "0 8px 8px"; for (const [k, t] of [["cx", "Most complex first"], ["hints", "Algorithms first"], ["calls", "Most connected first"], ["name", "By name"]]) { const o = el("option", null, t); o.value = k; sort.append(o); }
    sort.value = S.fnSort || "cx"; side.append(f, sort);
    const list = el("div", "pbody"); side.append(list);
    const m = await model(); if (S.active !== "logic") return;
    const all = Object.entries(m.functions).filter(([, fn]) => !/(^|\/)tests?\//.test(fn.file));
    const draw = () => {
      list.replaceChildren(); const q = S.fnFilter.toLowerCase();
      let rows = all.filter(([id]) => !q || id.toLowerCase().includes(q));
      const by = { cx: (a, b) => b[1].complexity - a[1].complexity, hints: (a, b) => b[1].hints.length - a[1].hints.length || b[1].complexity - a[1].complexity,
        calls: (a, b) => (b[1].callers.length + b[1].callees.length) - (a[1].callers.length + a[1].callees.length), name: (a, b) => a[0].localeCompare(b[0]) }[S.fnSort || "cx"];
      rows.sort(by);
      for (const [id, fn] of rows.slice(0, 500)) {
        const r = el("div", "fnrow" + (S.fnSel === id ? " sel" : "")); r.append(el("span", "nm", fn.qual + "()"), cxBadge(fn.complexity), el("span", "sub", `${fn.file}:${fn.line} · ${fn.callees.length} calls · ${fn.callers.length} callers`));
        if (fn.hints.length) { const h = el("div", "hints"); h.style.gridColumn = "1 / -1"; fn.hints.slice(0, 3).forEach((x) => h.append(el("span", "hint", x))); r.append(h); }
        r.onclick = () => { S.fnSel = id; draw(); select({ kind: "function", ref: id, file: fn.file, line: fn.line }); drawFlow(id); };
        list.append(r);
      }
      if (!rows.length) list.append(el("div", "empty", "No functions match."));
    };
    inp.oninput = debounce(() => { S.fnFilter = inp.value; draw(); }, 120); sort.onchange = () => { S.fnSort = sort.value; draw(); };
    draw();
    const drawFlow = (id) => { content.replaceChildren(); flowInto(content, id, "logic"); };
    if (S.fnSel && m.functions[S.fnSel]) drawFlow(S.fnSel);
    else { const top = all.sort((a, b) => b[1].complexity - a[1].complexity)[0]; if (top) { S.fnSel = top[0]; draw(); drawFlow(top[0]); } else content.append(el("div", "empty", "No functions yet.")); }
  }
  async function flowView(v, fid) { flowInto(v, fid, "flow:" + fid); }
  async function flowInto(v, fid, tabId) {
    const bar = vbar(short(fid) + "()"); v.append(bar);
    const vs = S.view[tabId + ":" + fid] = S.view[tabId + ":" + fid] || { k: 1, x: 20, y: 20, fit: true };
    const note = el("span", "note"); bar.append(note, el("span", "spacer"));
    const cg = el("button", "btn sm"); cg.append(icon("graph"), document.createTextNode("Call graph")); cg.onclick = () => { openTab({ id: "d:calls", title: "Call graph", icon: "graph" }); S.view["d:calls"] = { k: 1, x: 20, y: 20, focus: fid, fit: true }; renderView(); };
    const code = el("button", "btn sm"); code.append(icon("code"), document.createTextNode("Code")); bar.append(cg, code, el("span", "sep"));
    const canvas = el("div", "canvas"); v.append(canvas); const z = zoomControls(bar, canvas, vs);
    canvas.append(el("div", "msg", "Drawing…"));
    let d; try { d = await api(url(P("flow"), { fid, step: stepParam() })); } catch (e) { canvas.replaceChildren(el("div", "msg", "No flowchart for this function.")); return; }
    const fn = d.function;
    note.textContent = `${fn.file}:${fn.line}-${fn.end} · complexity ${fn.complexity}` + (d.kind === "outline" ? " · outline (JS/TS: branches and calls in order)" : "") + (d.truncated ? " · long: later parts collapsed" : "");
    code.onclick = () => openFile(fn.file, fn.line);
    const nodes = {}; for (const [k, n] of Object.entries(d.nodes)) nodes[k] = { kind: "line", ref: n.label, file: fn.file, line: n.line };
    await drawMermaid(canvas, { ...d, nodes }, vs, z, (k, info) => select({ kind: "function", ref: fid, file: fn.file, line: info.line }), (k, info) => openFile(fn.file, info.line));
  }

  // ---- concepts
  function conceptsView(v) {
    const bar = vbar("Mechanisms & concepts"); v.append(bar);
    const mapBtn = el("button", "btn sm"); mapBtn.append(icon("graph"), document.createTextNode("Concept map")); mapBtn.onclick = () => openTab({ id: "d:concepts", title: "Concept map", icon: "graph" });
    bar.append(el("span", "note", "Detected in the code, and claimed by the agent (claims are checked)"), el("span", "spacer"), mapBtn);
    const sc = el("div", "scroll"); v.append(sc);
    const groups = {}; for (const c of S.st.concepts) (groups[c.group] = groups[c.group] || []).push(c);
    if (!S.st.concepts.length) sc.append(el("div", "empty", "No mechanisms detected yet."));
    for (const [g, cs] of Object.entries(groups)) {
      sc.append(el("div", "section-title", g[0].toUpperCase() + g.slice(1)));
      const grid = el("div", "grid2");
      for (const c of cs) {
        const cardEl = el("div", "card ccard" + (S.sel?.kind === "concept" && S.sel.ref === c.id ? " sel" : "")); if (S.sel?.ref === c.id) cardEl.style.borderColor = "var(--accent)";
        const top = el("div", "top"), ic = el("div", "cic"); ic.append(icon(c.icon)); const t = el("div"); t.append(el("h4", null, c.title), el("p", null, c.meaning)); top.append(ic, t); cardEl.append(top);
        for (const e of c.evidence.slice(0, 4)) { const r = el("div", "ev"); r.append(el("span", "f mono", `${e.file}:${e.line}`), el("span", "s", (e.symbol ? e.symbol + " · " : "") + e.signal)); r.onclick = () => openFile(e.file, e.line); cardEl.append(r); }
        for (const cl of c.claims) { const r = el("div", "ev"); r.append(el("span", "badge " + cl.status, cl.status), el("span", "f mono", cl.symbol), el("span", "s", cl.reason || "")); r.onclick = () => cl.file && openFile(cl.file, cl.line); cardEl.append(r); }
        cardEl.onclick = (e) => { if (!e.target.closest(".ev")) select({ kind: "concept", ref: c.id }); };
        grid.append(cardEl);
      }
      sc.append(grid);
    }
  }

  // ---- timeline
  function timelineView(v) {
    const bar = vbar("Timeline · every step of the agent's work"); v.append(bar); bar.append(el("span", "note", "Click a step to view every diagram as it was then"), el("span", "spacer"));
    const rec = el("button", "btn sm primary"); rec.append(icon("flag"), document.createTextNode("Record step")); rec.onclick = recordStep; bar.append(rec);
    const sc = el("div", "scroll"), tl = el("div", "tl"); sc.append(tl); v.append(sc);
    const st = S.st, last = st.steps[st.steps.length - 1];
    const liveEl = el("div", "tstep live" + (S.step === "live" ? " on" : "")); const h = el("div", "h"); h.append(el("span", "n", "now"), el("span", "ttl", st.pending.length ? "Work in progress" : "No changes since the last step"), el("span", "badge auto", "LIVE"));
    liveEl.append(h); if (st.pending.length) liveEl.append(changeList(st.pending, last ? String(last.n) : "live", "live"));
    liveEl.onclick = () => setStep("live"); tl.append(liveEl);
    for (const s of [...st.steps].reverse()) {
      const e = el("div", "tstep" + (S.step === s.n ? " on" : "")); const hh = el("div", "h");
      hh.append(el("span", "n", "#" + s.n), el("span", "ttl", s.title), el("span", "badge " + s.source, s.source), el("span", "when", `${clock(s.ts)} · ${ago(s.ts)}`)); e.append(hh);
      if (s.intent) e.append(el("div", "prompt", s.intent));
      else if (s.prompt && s.prompt !== s.title) e.append(el("div", "prompt", "prompt: " + s.prompt));
      if (s.n > 0) e.append(deltaChips(s.summary));
      if (s.title_check && s.title_check !== "ok") { const w = el("div", "chips"); w.append(el("span", "chip warn", "⚠ " + s.title_check)); e.append(w); }
      if (s.changes?.length) e.append(changeList(s.changes.slice(0, 14), String(Math.max(0, s.n - 1)), String(s.n)));
      e.onclick = () => setStep(s.n);
      tl.append(e);
    }
  }
  function setStep(n) { S.step = n; S.base = "auto"; S.model = null; for (const k of Object.keys(S.view)) if (S.view[k]) S.view[k].fit = true; renderAll(); }

  // ---- files & diffs
  const KW = { python: "def class return if elif else for while in not and or is None True False import from as with try except finally raise yield async await lambda pass break continue global nonlocal assert del match case self",
    js: "function const let var return if else for while do switch case break continue new class extends import from export default async await try catch finally throw typeof instanceof in of null undefined true false this super yield interface type enum implements public private protected readonly static",
    sql: "select from where insert into values update set delete create table primary key foreign references not null unique index join left right inner outer on group by order having limit as and or default" };
  function highlight(line, lang) {
    const kws = new Set((KW[lang] || KW.js).split(" ")); const sqlish = lang === "sql";
    const re = lang === "python" ? /(#.*$)|("""[^]*?"""|'''[^]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(@[\w.]+)|(\b\d[\d_.]*\b)|(\b[A-Za-z_]\w*\b)/g
      : sqlish ? /(--.*$)|('(?:''|[^'])*')|(@@)|(\b\d+\b)|(\b[A-Za-z_]\w*\b)/g
      : /(\/\/.*$|\/\*.*?\*\/)|(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(@\w+)|(\b\d[\d_.]*\b)|(\b[A-Za-z_$][\w$]*\b)/g;
    let out = "", last = 0, m, prev = "";
    while ((m = re.exec(line))) {
      out += esc(line.slice(last, m.index)); const t = m[0];
      if (m[1]) out += `<span class="tok-c">${esc(t)}</span>`; else if (m[2]) out += `<span class="tok-s">${esc(t)}</span>`; else if (m[3]) out += `<span class="tok-d">${esc(t)}</span>`;
      else if (m[4]) out += `<span class="tok-n">${esc(t)}</span>`;
      else if (kws.has(sqlish ? t.toLowerCase() : t)) out += `<span class="tok-k">${esc(t)}</span>`;
      else if (/^(def|function|class)$/.test(prev) || line.slice(re.lastIndex).startsWith("(")) out += `<span class="tok-f">${esc(t)}</span>`;
      else out += esc(t);
      prev = m[5] ? t : prev; last = re.lastIndex;
    }
    return out + esc(line.slice(last));
  }
  async function fileView(v, path) {
    const bar = vbar(path); v.append(bar); const note = el("span", "note"); bar.append(note, el("span", "spacer"));
    const steps = S.st.steps, cmpFrom = S.step === "live" ? (steps.length ? String(steps[steps.length - 1].n) : null) : String(Math.max(0, S.step - 1));
    const db = el("button", "btn sm"); db.append(icon("diff"), document.createTextNode("Diff with previous step")); db.onclick = () => openDiff(path, cmpFrom, stepParam()); bar.append(db);
    const box = el("div", "code"); v.append(box);
    let f; try { f = await api(url(P("file"), { path, step: stepParam() })); } catch (e) { box.append(el("div", "empty", "This file is not tracked at this step.")); return; }
    if (f.secret || f.binary || f.text == null) { box.append(el("div", "empty", f.secret ? "Secret-looking file: Mapwright tracks that it changed, but never reads or shows its content." : "Binary or very large file: not shown.")); return; }
    note.textContent = `${f.lang} · ${f.text.split("\n").length} lines` + (S.step !== "live" ? ` · as of step ${S.step}` : "");
    const defs = {}; for (const s of f.symbols || []) if (s.kind === "function") defs[s.line] = s;
    let marks = {};
    if (cmpFrom != null && cmpFrom !== stepParam()) {
      try { const d = await api(url(P("diff"), { path, from: cmpFrom, to: stepParam() })); let ln = 0; for (const l of d.diff.split("\n")) { const h = l.match(/^@@ -\d+(?:,\d+)? \+(\d+)/); if (h) { ln = +h[1]; continue; } if (l.startsWith("+++") || l.startsWith("---")) continue; if (l.startsWith("+")) { marks[ln] = "add"; ln++; } else if (l.startsWith("-")) { marks[ln] = marks[ln] || "chg"; } else ln++; } } catch (e) {}
    }
    const lang = f.lang === "python" ? "python" : f.lang === "sql" ? "sql" : "js";
    const frag = document.createDocumentFragment(); const lines = f.text.split("\n");
    lines.forEach((l, i) => {
      const n = i + 1, row = el("div", "ln" + (marks[n] ? " " + marks[n] : "") + (defs[n] ? " def" : "")); row.id = "L" + n;
      const g = el("span", "g"); const fn = el("span", "fn", "ƒ"); if (defs[n]) { fn.title = "Flowchart of " + defs[n].qual; fn.onclick = () => openFlow(defs[n].fid); }
      g.append(fn, document.createTextNode(String(n)), el("span", "mk")); const t = el("span", "t"); t.innerHTML = lang === "python" || lang === "js" || lang === "sql" ? highlight(l, lang) : esc(l);
      row.append(g, t); frag.append(row);
    });
    box.append(frag);
    const want = (S.view["file:" + path] || {}).line; if (want) { const r = box.querySelector("#L" + want); if (r) { r.classList.add("hl"); requestAnimationFrame(() => r.scrollIntoView({ block: "center" })); } }
  }
  async function diffView(v, path, from, to) {
    const bar = vbar(`${path}`); v.append(bar); bar.append(el("span", "note", `step ${from} → ${to === "live" ? "now" : "step " + to}`), el("span", "spacer"));
    const ob = el("button", "btn sm", "Open file"); ob.onclick = () => openFile(path); bar.append(ob);
    const box = el("div", "diffv"); v.append(box);
    try {
      const d = await api(url(P("diff"), { path, from, to }));
      if (d.secret) { box.append(el("div", "empty", "Secret-looking file: content not read.")); return; }
      if (!d.diff) { box.append(el("div", "empty", "No differences.")); return; }
      for (const l of d.diff.split("\n")) box.append(el("div", l.startsWith("@@") ? "h" : l.startsWith("+++") || l.startsWith("---") ? "m" : l.startsWith("+") ? "a" : l.startsWith("-") ? "r" : "", l || " "));
    } catch (e) { box.append(el("div", "empty", "Diff not available.")); }
  }

  // ---- setup
  async function setupView(v) {
    const bar = vbar("Connect an agent"); v.append(bar); bar.append(el("span", "note", "Works with any MCP-capable agent; anything else is tracked from the files"), el("span", "spacer"));
    const sc = el("div", "scroll"); v.append(sc);
    let integ = S.integ; try { integ = await api(url("/v1/integrations", { key: S.key })); S.integ = integ; renderToolbar(); } catch (e) {}
    const any = (integ?.targets || []).some((t) => Object.values(t.scopes || {}).some((x) => x.connected));
    const steps = el("div", "steps-h");
    [["Track the project", !!S.st], ["Connect an agent", any], ["Tell the agent (optional)", false], ["Open the map in your editor (optional)", false]].forEach(([t, ok], i) => { const s = el("div", "s" + (ok ? " done" : "")); s.append(el("b", null, ok ? "✓" : String(i + 1)), document.createTextNode(t)); steps.append(s); });
    sc.append(steps);
    sc.append(el("div", "section-title", "1 · Project"));
    const pc = el("div", "card"); const kv = el("dl", "kv"); kv.append(el("dt", null, "Tracking"), el("dd", "mono", S.st.root), el("dt", null, "Steps"), el("dd", null, String(S.st.steps.length)));
    const add = el("div", "actions"); add.style.marginTop = "12px"; const inp = el("input", "input"); inp.placeholder = "Track another folder: /path/to/project"; inp.style.flex = "1";
    const go = el("button", "btn", "Track"); go.onclick = async () => { try { const r = await api("/v1/projects", { root: inp.value.trim() }); S.key = r.key; saveUI(); location.reload(); } catch (e) { if (e.message !== "demo") toast("err", "Could not track that folder", e.message); } };
    add.append(inp, go); pc.append(kv, add); sc.append(pc);
    sc.append(el("div", "section-title", "2 · Agent"));
    const grid = el("div", "agents"); sc.append(grid);
    for (const t of integ?.targets || []) {
      const c = el("div", "card agent"); const h = el("div", "h"); h.append(icon(t.manual ? "doc" : "robot"), el("b", null, t.title)); if (t.installed) h.append(el("span", "badge ok", "found")); c.append(h, el("div", "how", t.how));
      const st = el("div", "st"); for (const [scope, info] of Object.entries(t.scopes || {})) st.append(el("span", "chip" + (info.connected ? " ok" : ""), `${scope}${info.connected ? " ✓" : ""}`)); c.append(st);
      const acts = el("div", "actions");
      for (const [scope, info] of Object.entries(t.scopes || {})) {
        if (info.path === null) continue;
        const b = el("button", "btn sm" + (info.connected ? " danger" : scope === "project" ? " primary" : ""), info.connected ? `Disconnect ${scope}` : `Connect ${scope === "project" ? "this project" : "all projects"}`);
        b.title = info.path || ""; b.onclick = async () => { try { const r = await api(info.connected ? "/v1/disconnect" : "/v1/connect", { target: t.id, scope, key: S.key }); toast("ok", info.connected ? "Disconnected" : "Connected", (r.files || []).join(", ") + (info.connected ? "" : " · restart the agent so it loads Mapwright.")); S.integ = { targets: r.targets }; renderView(); renderToolbar(); } catch (e) { if (e.message !== "demo") toast("err", "Could not change the config", e.message); } };
        acts.append(b);
      }
      const sh = el("button", "btn sm", "Show config"); const snip = el("div", "snip"); snip.hidden = true; const pre = el("pre", null, t.snippet); const cp = el("button", "btn sm", "Copy"); cp.onclick = () => { navigator.clipboard?.writeText(t.snippet); toast("ok", "Copied", "Paste it into the agent's MCP settings."); }; snip.append(pre, cp);
      sh.onclick = () => { snip.hidden = !snip.hidden; }; acts.append(sh); c.append(acts, snip); grid.append(c);
    }
    sc.append(el("div", "section-title", "3 · Tell the agent"));
    const tc = el("div", "card"); tc.append(el("p", null, "Adds six lines to your agent instructions file so it starts from the map, records steps and keeps its plan in Mapwright. Optional: the MCP server already carries short instructions."));
    const ta = el("div", "actions"); ta.style.marginTop = "10px";
    for (const f of ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules"]) { const b = el("button", "btn sm", "Add to " + f); b.onclick = async () => { try { const r = await api("/v1/agents-md", { key: S.key, file: f }); toast("ok", "Written", r.path); } catch (e) { if (e.message !== "demo") toast("err", "Could not write", e.message); } }; ta.append(b); }
    tc.append(ta); sc.append(tc);
    sc.append(el("div", "section-title", "4 · In your editor"));
    const ec = el("div", "card"); ec.append(el("p", null, "VS Code, Cursor and Windsurf: install the Mapwright extension (mapwright-vscode.vsix in the download). It opens this map beside your code, shows the current step in the status bar and can record steps. JetBrains IDEs: open this page in the built-in browser, or keep it in a window next to the IDE."));
    const cmd = el("div", "snip"); cmd.style.marginTop = "10px"; const cpre = el("pre", null, "code --install-extension integrations/vscode/mapwright-vscode-0.1.0.vsix"); cmd.append(cpre); ec.append(cmd); sc.append(ec);
  }

  // ------------------------------------------------------------------ inspector & brief
  async function select(sel) { S.sel = sel; if (!S.rightOpen || (S.rightMode && S.rightMode !== "inspector")) { S.rightMode = "inspector"; S.rightOpen = true; renderAll(); } else renderRight(); renderStatus(); if (S.left === "structure" && sel.file) renderLeft(); if (S.left === "project") renderLeft(); }
  async function renderRight() {
    const body = $("#right-body"); body.replaceChildren();
    if ((S.rightMode || "inspector") === "brief") { $("#right-title").textContent = "Agent brief"; briefPanel(body); return; }
    $("#right-title").textContent = "Inspector";
    const sel = S.sel; const box = el("div", "insp"); body.append(box);
    if (!sel || !S.st) { box.append(el("div", "empty", "Click any box in a diagram, a file, a function or a mechanism to see what it is, where it lives and how it connects. Double-click opens it.")); return; }
    const kindName = { function: "Function", class: "Class", table: "Table", module: "Module", file: "File", infra: "Infrastructure", concept: "Mechanism", route: "Entry point", dir: "Folder", package: "Package", layer: "Layer", line: "Code" }[sel.kind] || sel.kind;
    box.append(el("div", "kind", kindName));
    if (["function", "class", "table", "module"].includes(sel.kind)) {
      box.append(el("h2", null, short(sel.ref)));
      if (sel.file) { const l = el("div", "loc mono", `${sel.file}${sel.line ? ":" + sel.line : ""}`); l.onclick = () => openFile(sel.file, sel.line); box.append(l); }
      const pre = el("pre", "cardtxt", "…"); box.append(pre);
      const acts = el("div", "actions"); box.append(acts);
      if (sel.kind === "function") { const f = el("button", "btn sm primary"); f.append(icon("function"), document.createTextNode("Flowchart")); f.onclick = () => openFlow(sel.ref); const g = el("button", "btn sm"); g.append(icon("graph"), document.createTextNode("Call graph")); g.onclick = () => { openTab({ id: "d:calls", title: "Call graph", icon: "graph" }); S.view["d:calls"] = { k: 1, x: 20, y: 20, focus: sel.ref, fit: true }; renderView(); }; acts.append(f, g); }
      if (sel.file) { const o = el("button", "btn sm"); o.append(icon("code"), document.createTextNode("Open")); o.onclick = () => openFile(sel.file, sel.line); acts.append(o); }
      const cp = el("button", "btn sm"); cp.append(icon("copy"), document.createTextNode("Copy ref")); cp.onclick = () => { navigator.clipboard?.writeText(sel.ref); toast("ok", "Copied", sel.ref); }; acts.append(cp);
      try { const r = await api(url(P("symbol"), { ref: sel.ref })); pre.textContent = r.card; } catch (e) { pre.textContent = "Details are not available here."; }
    } else if (sel.kind === "file") {
      const f = S.st.files.find((x) => x.path === sel.ref) || { path: sel.ref };
      box.append(el("h2", null, base(sel.ref)), el("div", "loc mono", sel.ref));
      const kv = el("dl", "kv"); [["language", f.lang], ["layer", f.layer], ["lines", f.lines], ["functions", f.functions], ["classes", f.classes], ["status", f.status ? { A: "added since the last step", M: "modified since the last step", D: "deleted" }[f.status] : "unchanged"]].forEach(([k, val]) => { if (val != null && val !== "") kv.append(el("dt", null, k), el("dd", null, String(val))); });
      box.append(kv);
      if (f.secret) box.append(el("div", "chip warn", "secret-looking: never read"));
      const acts = el("div", "actions"); const o = el("button", "btn sm primary", "Open"); o.onclick = () => openFile(sel.ref); acts.append(o);
      if (f.status === "M" || f.status === "A") { const d = el("button", "btn sm", "Diff"); const last = S.st.steps[S.st.steps.length - 1]; d.onclick = () => openDiff(sel.ref, last ? String(last.n) : "live", "live"); acts.append(d); }
      box.append(acts);
    } else if (sel.kind === "component") {
      const c = S.sysComps && S.sysComps[sel.ref]; if (!c) return;
      box.append(el("h2", null, c.title), el("div", "sysdesc", c.desc));
      const kv = el("dl", "kv"); for (const [k, val] of c.stats) kv.append(el("dt", null, k), el("dd", null, String(val))); box.append(kv);
      for (const sec of c.sections) {
        if (!sec.rows.length) continue;
        box.append(el("div", "kind", sec.title));
        for (const r of sec.rows.slice(0, 40)) { const row = el("div", "ev link"); row.append(el("span", null, r.label)); if (r.meta) row.append(el("span", "meta", r.meta)); row.onclick = r.run; box.append(row); }
        if (sec.rows.length > 40) box.append(el("div", "empty", `+${sec.rows.length - 40} more`));
      }
    } else if (sel.kind === "infra") {
      const n = S.st.infra.nodes.find((x) => x.id === sel.ref); if (!n) return;
      box.append(el("h2", null, n.label)); const kv = el("dl", "kv"); kv.append(el("dt", null, "kind"), el("dd", null, n.kind), el("dt", null, "detail"), el("dd", null, n.detail || "—"), el("dt", null, "found in"), el("dd", null, n.sources.join(", "))); box.append(kv);
      const out = S.st.infra.edges.filter((e) => e.from === n.id || e.to === n.id); if (out.length) { box.append(el("div", "kind", "Connections")); for (const e of out) box.append(el("div", "ev", `${e.from === n.id ? "→" : "←"} ${e.label} ${e.from === n.id ? e.to : e.from}`)); }
      const src = n.sources.find((s) => S.st.files.some((f) => f.path === s)); if (src) { const o = el("button", "btn sm", "Open " + base(src)); o.onclick = () => openFile(src); box.append(o); }
    } else if (sel.kind === "concept") {
      const c = S.st.concepts.find((x) => x.id === sel.ref); if (!c) return;
      const h = el("h2"); h.append(icon(c.icon), document.createTextNode(" " + c.title)); box.append(h, el("p", null, c.meaning));
      box.append(el("div", "kind", "Evidence in the code")); for (const e of c.evidence) { const r = el("div", "ev"); r.append(el("span", "f mono", `${e.file}:${e.line}`), el("span", "s", e.signal)); r.onclick = () => openFile(e.file, e.line); box.append(r); }
      if (c.claims.length) { box.append(el("div", "kind", "Claimed by the agent")); for (const cl of c.claims) { const r = el("div", "ev"); r.append(el("span", "badge " + cl.status, cl.status), el("span", "f mono", cl.symbol)); box.append(r, el("div", "s", cl.reason || "")); } }
    } else if (sel.kind === "route") {
      box.append(el("h2", null, sel.ref)); if (sel.file) { const l = el("div", "loc mono", `${sel.file}:${sel.line || ""}`); l.onclick = () => openFile(sel.file, sel.line); box.append(l); }
      const r = S.st.routes.find((x) => `${x.method} ${x.path}` === sel.ref); if (r?.fid) { const b = el("button", "btn sm primary", "Handler flowchart"); b.onclick = () => openFlow(r.fid); box.append(b); }
    } else if (sel.kind === "line") {
      box.append(el("h2", null, sel.ref || "line"), el("div", "loc mono", `${sel.file}:${sel.line}`));
    } else { box.append(el("h2", null, sel.ref || "")); }
  }
  async function briefPanel(body) {
    const box = el("div", "insp"); body.append(box);
    box.append(el("p", null, "What the agent reads instead of exploring files. No source code; it points at file:line so the agent opens only what it needs."));
    const pre = el("pre", "cardtxt", S.brief ? S.brief.text : "…"); box.append(pre);
    const acts = el("div", "actions"); const cp = el("button", "btn sm", "Copy"); cp.onclick = () => { navigator.clipboard?.writeText(pre.textContent); toast("ok", "Copied", "Paste it into any agent's context."); }; acts.append(cp); box.append(acts);
    if (!S.brief) try { S.brief = await api(url(P("brief"), {})); pre.textContent = S.brief.text; renderStatus(); } catch (e) { pre.textContent = "Not available."; }
    if (S.brief) box.append(el("div", "kind", `${S.brief.chars} characters · about ${S.brief.tokens} tokens`));
  }

  // ------------------------------------------------------------------ bottom panel
  function renderBottom() {
    const tabs = $("#btabs"), body = $("#bbody"); tabs.replaceChildren(); body.replaceChildren();
    if (!S.st) return;
    const counts = { steps: S.st.steps.length, todo: S.st.todos.filter((t) => t.status === "open").length, problems: S.st.problems.length, activity: "" };
    for (const [id, ic, title] of BOTTOM) { const b = el("button", "btab" + (S.btab === id ? " on" : "")); b.append(icon(ic), document.createTextNode(title)); if (counts[id]) b.append(el("span", "n", String(counts[id]))); b.onclick = () => { S.btab = id; saveUI(); renderBottom(); renderStripes(); }; tabs.append(b); }
    tabs.append(el("span", "grow")); const hide = el("button", "tbtn"); hide.title = "Hide"; hide.append(icon("close")); hide.onclick = () => { S.bottomOpen = false; saveUI(); renderAll(); }; tabs.append(hide);
    if (S.btab === "steps") {
      for (const s of [...S.st.steps].reverse()) { const r = el("div", "bl" + (S.step === s.n ? " ok" : "")); r.style.cursor = "pointer"; r.append(icon("flag"), el("span", "when", "#" + s.n), el("span", "txt", s.title), el("span", "badge " + s.source, s.source), el("span", "tag", `${s.summary.files} files +${s.summary.added}/−${s.summary.removed}`), el("span", "when", ago(s.ts))); r.onclick = () => setStep(s.n); body.append(r); }
    } else if (S.btab === "todo") {
      const add = el("div", "addrow"); const inp = el("input", "input"); inp.placeholder = "Add a todo for the agent (it sees it in the map)"; const b = el("button", "btn sm primary", "Add");
      const doAdd = async () => { if (!inp.value.trim()) return; try { await api(P("todo"), { action: "add", text: inp.value.trim() }); inp.value = ""; await load(false); } catch (e) { if (e.message !== "demo") toast("err", "Could not add", e.message); } };
      b.onclick = doAdd; inp.onkeydown = (e) => { if (e.key === "Enter") doAdd(); }; add.append(inp, b); body.append(add);
      for (const t of S.st.todos) { const r = el("div", "bl" + (t.status === "done" ? (t.verified ? " ok" : " warn") : "")); r.append(icon(t.status === "done" ? (t.verified ? "check-square" : "warning") : "check"), el("span", "when", t.id), el("span", "txt", t.text), el("span", "tag", t.status === "done" ? (t.verified ? "done · verified" : "done · " + (t.reason || "unverified")) : t.status + (t.by === "user" ? " · from you" : ""))); body.append(r); }
      if (!S.st.todos.length) body.append(el("div", "empty", "No todos yet."));
    } else if (S.btab === "problems") {
      if (!S.st.problems.length) body.append(el("div", "bl ok", null)), body.lastChild.append(icon("check"), el("span", "txt", "Everything the agent claimed checks out against the code."));
      for (const x of S.st.problems) { const r = el("div", "bl warn"); r.append(icon("warning"), el("span", "badge " + x.status, x.kind), el("span", "txt", x.text)); body.append(r); }
    } else {
      for (const e of [...S.st.activity].reverse()) {
        const txt = e.t === "prompt" ? "prompt: " + (e.text || "") : e.t === "tool" ? `${e.tool} ${(e.files || []).join(", ")}` : e.t === "step" ? `step ${e.n}: ${e.title}` : e.t === "turn_end" ? "agent finished its turn" : e.t === "todo" ? `todo ${e.tid}: ${e.text}` : e.t === "todo_done" ? `todo ${e.tid} done` : e.t === "claim" ? `claim ${e.concept} → ${e.symbol}` : e.t === "note" ? `note ${e.symbol}: ${e.role}` : e.t;
        const r = el("div", "bl"); r.append(icon({ prompt: "user", tool: "terminal", step: "flag", turn_end: "check", todo: "check-square", todo_done: "check-square", claim: "puzzle", note: "doc" }[e.t] || "activity"), el("span", "when", clock(e.ts)), el("span", "txt", txt), el("span", "tag", e.agent || "")); body.append(r);
      }
      if (!S.st.activity.length) body.append(el("div", "empty", "No agent activity recorded yet. Connected agents report prompts, edits and steps here."));
    }
  }

  // ------------------------------------------------------------------ status bar
  function renderStatus() {
    const s = $("#status"); s.replaceChildren();
    const crumbs = el("div", "crumbs"); const tab = allTabs().find((t) => t.id === S.active);
    if (S.st) crumbs.append(el("b", null, S.st.name)); if (tab) crumbs.append(document.createTextNode(" › " + (tab.hint || tab.title)));
    if (S.sel && S.sel.ref) crumbs.append(document.createTextNode(" › " + short(S.sel.ref)));
    s.append(crumbs);
    if (S.st) {
      s.append(el("span", "it", `${S.st.counts.files} files indexed`));
      if (S.brief) { const b = el("span", "it", `brief ≈ ${S.brief.tokens} tokens`); b.title = "Size of the map an agent reads instead of exploring the code"; s.append(b); }
      const st = el("span", "it", S.step === "live" ? `live · ${S.st.steps.length} steps` : `viewing step ${S.step}`); s.append(st);
    }
    const c = el("span", "it"); const dot = el("span", "ldot " + (S.conn === "live" ? "on" : S.conn === "demo" ? "" : "off")); c.append(dot, document.createTextNode({ live: "connected", demo: "demo data", offline: "daemon offline", token: "unauthorised", connecting: "connecting…" }[S.conn] || S.conn)); s.append(c);
  }

  // ------------------------------------------------------------------ actions, menus, palette, settings, toasts
  async function recordStep() {
    const title = prompt("Step title (what was done). The changed files are computed by Mapwright.");
    if (!title) return;
    try { const r = await api(P("step"), { title }); toast("ok", "Step recorded", r.receipt); await load(false); } catch (e) { if (e.message !== "demo") toast("err", "Could not record", e.message); }
  }
  function toast(kind, title, text) {
    const t = el("div", "toast " + kind); t.append(icon(kind === "ok" ? "check" : kind === "err" ? "warning" : "info")); const b = el("div"); b.append(el("b", null, title), el("span", null, text || "")); t.append(b);
    $("#toasts").append(t); setTimeout(() => t.remove(), 4500);
  }
  function menu(anchor, items) {
    closeMenus(); const m = el("div", "menu"); const r = anchor.getBoundingClientRect(); m.style.left = r.left + "px"; m.style.top = r.bottom + 4 + "px";
    for (const it of items) { if (it === "-") { m.append(el("hr")); continue; } if (it.header) { m.append(el("div", "mh", it.header)); continue; } const mi = el("div", "mi"); if (it.icon) mi.append(icon(it.icon)); mi.append(el("span", null, it.label)); if (it.meta) mi.append(el("span", "meta", it.meta)); mi.onclick = () => { closeMenus(); it.run(); }; m.append(mi); }
    const scrim = el("div"); scrim.style.cssText = "position:fixed;inset:0;z-index:39"; scrim.onclick = closeMenus; scrim.dataset.menu = "1"; m.dataset.menu = "1";
    document.body.append(scrim, m);
  }
  function closeMenus() { document.querySelectorAll("[data-menu]").forEach((x) => x.remove()); }
  async function palette() {
    if (!DEMO && !S.st) return;
    closeMenus(); const scrim = el("div", "scrim"); const p = el("div", "palette"); scrim.dataset.menu = p.dataset.menu = "1";
    const head = el("div", "ph"); head.append(icon("search")); const inp = el("input"); inp.placeholder = "Search files, symbols, views and actions"; head.append(inp); const res = el("div", "pr"); p.append(head, res);
    document.body.append(scrim, p); scrim.onclick = closeMenus; inp.focus();
    const actions = [
      ...allTabs().map((t) => ({ grp: "Views", label: t.title, icon: t.icon || "file", run: () => openTab(t) })), { grp: "Views", label: "Call graph", icon: "graph", run: () => openTab({ id: "d:calls", title: "Call graph", icon: "graph" }) },
      { grp: "Views", label: "Concept map", icon: "graph", run: () => openTab({ id: "d:concepts", title: "Concept map", icon: "graph" }) },
      { grp: "Actions", label: "Record a step", icon: "flag", run: recordStep }, { grp: "Actions", label: "Connect an agent", icon: "plug", run: () => openTab({ id: "setup", title: "Connect an agent", icon: "plug" }) },
      { grp: "Actions", label: "Settings", icon: "gear", meta: "Ctrl+,", run: settings }, { grp: "Actions", label: "Toggle light / dark theme", icon: "sun", run: () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark") },
      { grp: "Actions", label: "Copy the agent brief", icon: "copy", run: async () => { const b = S.brief || await api(url(P("brief"), {})); navigator.clipboard?.writeText(b.text); toast("ok", "Copied", `${b.tokens} tokens`); } },
      { grp: "Actions", label: "Show live (latest)", icon: "history", run: () => setStep("live") },
    ];
    let items = [], act = 0;
    const draw = async () => {
      const q = inp.value.trim().toLowerCase(); items = [];
      const files = (S.st?.files || []).filter((f) => f.status !== "D" && (!q || f.path.toLowerCase().includes(q))).slice(0, q ? 8 : 4).map((f) => ({ grp: "Files", label: base(f.path), meta: f.path, icon: "file", run: () => openFile(f.path) }));
      const acts = actions.filter((a) => !q || a.label.toLowerCase().includes(q)).slice(0, q ? 8 : 6);
      items = [...acts, ...files];
      if (q.length >= 2 && S.key) { try { const r = await api(url(P("find"), { q })); if (inp.value.trim().toLowerCase() !== q) return; items = [...r.results.slice(0, 10).map((x) => ({ grp: "Symbols", label: short(x.id), meta: `${x.kind} · ${x.file}:${x.line || ""}`, icon: x.kind === "class" ? "class" : x.kind === "table" ? "table" : x.kind === "module" ? "file" : "function", run: () => x.kind === "function" ? (select({ kind: "function", ref: x.id, file: x.file, line: x.line }), openFlow(x.id)) : x.kind === "module" ? openFile(x.file) : (select({ kind: x.kind, ref: x.id, file: x.file, line: x.line }), openFile(x.file, x.line)) })), ...items]; } catch (e) {} }
      act = 0; render();
    };
    const render = () => { res.replaceChildren(); let g = null; items.forEach((it, i) => { if (it.grp !== g) { g = it.grp; res.append(el("div", "grp", g)); } const mi = el("div", "mi" + (i === act ? " act" : "")); mi.append(icon(it.icon), el("span", null, it.label)); if (it.meta) mi.append(el("span", "meta", it.meta)); mi.onclick = () => { closeMenus(); it.run(); }; res.append(mi); }); if (!items.length) res.append(el("div", "empty", "Nothing matches.")); };
    inp.oninput = debounce(draw, 90);
    inp.onkeydown = (e) => { if (e.key === "ArrowDown") { act = Math.min(items.length - 1, act + 1); render(); e.preventDefault(); } else if (e.key === "ArrowUp") { act = Math.max(0, act - 1); render(); e.preventDefault(); } else if (e.key === "Enter" && items[act]) { closeMenus(); items[act].run(); } else if (e.key === "Escape") closeMenus(); };
    draw();
  }
  async function settings() {
    closeMenus(); let data; try { data = await api("/v1/settings"); } catch (e) { data = { settings: { theme: store.get("theme", "dark"), font_size: 13 }, defaults: {}, version: "demo" }; }
    const s = { ...data.settings }; const scrim = el("div", "scrim"), m = el("div", "modal"); scrim.dataset.menu = m.dataset.menu = "1";
    const head = el("div", "mh2"); head.append(el("span", null, "Settings"), el("span", "grow")); const x = el("button", "tbtn"); x.append(icon("close")); x.onclick = closeMenus; head.append(x);
    const mb = el("div", "mb"), nav = el("div", "nav"), pane = el("div", "pane"); mb.append(nav, pane);
    const foot = el("div", "mf"); const msg = el("span", "msg"); const cancel = el("button", "btn", "Cancel"); const apply = el("button", "btn", "Apply"); const ok = el("button", "btn primary", "OK"); foot.append(msg, cancel, apply, ok);
    m.append(head, mb, foot); document.body.append(scrim, m); scrim.onclick = closeMenus; cancel.onclick = closeMenus;
    const field = (label, ctrl, help) => { const f = el("div", "field"); f.append(el("label", null, label), ctrl); if (help) f.append(el("div", "help", help)); return f; };
    const seg = (key, opts) => { const w = el("div", "seg"); for (const [v, t] of opts) { const b = el("button", s[key] === v ? "on" : null, t); b.onclick = () => { s[key] = v; [...w.children].forEach((c) => c.classList.toggle("on", c === b)); }; w.append(b); } return w; };
    const num = (key, min, max, step = 1) => { const i = el("input", "input"); i.type = "number"; i.min = min; i.max = max; i.step = step; i.value = s[key]; i.style.width = "120px"; i.oninput = () => { s[key] = step < 1 ? parseFloat(i.value) : parseInt(i.value, 10); }; return i; };
    const tog = (key) => { const i = el("input", "toggle"); i.type = "checkbox"; i.checked = !!s[key]; i.onchange = () => { s[key] = i.checked; }; return i; };
    const pages = {
      Appearance: () => [field("Theme", seg("theme", [["dark", "Dark"], ["light", "Light"]])), field("UI font size", num("font_size", 11, 16), "Applies to panels and diagrams.")],
      Tracking: () => [field("Close steps", seg("auto_step", [["turn", "At each turn end"], ["idle", "After a quiet period"], ["off", "Only when asked"]]), "Turn ends come from agent hooks. Without hooks, steps close after the quiet period."),
        field("Quiet period (s)", num("idle_seconds", 5, 3600)), field("Scan interval (s)", num("watch_interval", 0.5, 60, 0.5), "How often the daemon checks tracked projects for changes.")],
      Analysis: () => { const i = el("input", "input"); i.value = (s.ignore || []).join(", "); i.oninput = () => { s.ignore = i.value.split(",").map((x) => x.trim()).filter(Boolean); }; return [field("Folders to skip", i, "Names, comma-separated. node_modules, .venv, dist, build and similar are always skipped."), field("Maximum files", num("max_files", 100, 50000))]; },
      Agents: () => [field("Brief size (characters)", num("brief_budget", 400, 20000, 100), "About four characters per token. 2400 ≈ 600 tokens."), field("Redact secrets in code views", tog("redact"))],
      Integrations: () => { const b = el("button", "btn", "Open Connect an agent"); b.onclick = () => { closeMenus(); openTab({ id: "setup", title: "Connect an agent", icon: "plug" }); }; return [el("p", null, "Connect Claude Code, Cursor, VS Code, Windsurf, opencode, Codex, Gemini CLI and others."), Object.assign(el("div"), { style: "margin-top:12px" }), b]; },
      About: () => { const kv = el("dl", "kv"); [["Version", data.version], ["Data folder", data.home || "—"], ["Port", data.port || "—"], ["Mode", DEMO ? "demo (read-only)" : "local daemon"]].forEach(([k, v]) => kv.append(el("dt", null, k), el("dd", "mono", String(v)))); return [kv, Object.assign(el("p"), { textContent: "Everything stays on this machine. Nothing is sent anywhere.", style: "margin-top:14px;color:var(--muted)" }), ...(DEMO ? [] : [Object.assign(el("p"), { textContent: "The access token is kept in this browser so you do not need the link every time.", style: "margin-top:14px;color:var(--muted)" }), Object.assign(el("button", "btn", "Forget token"), { id: "forget-token", onclick: forgetToken })])]; },
    };
    let cur = "Appearance";
    const show = () => { nav.replaceChildren(); for (const k of Object.keys(pages)) { const r = el("div", "row" + (k === cur ? " sel" : ""), k); r.onclick = () => { cur = k; show(); }; nav.append(r); } pane.replaceChildren(el("h3", null, cur), ...pages[cur]()); };
    show();
    const save = async () => { setTheme(s.theme); document.documentElement.style.setProperty("--ui", (s.font_size || 13) + "px"); const changes = {}; for (const [k, v] of Object.entries(s)) if (JSON.stringify(v) !== JSON.stringify(data.settings[k])) changes[k] = v;
      if (!Object.keys(changes).length || DEMO) { msg.textContent = DEMO ? "Demo: appearance applied in this browser only" : "No changes"; return true; }
      try { const r = await api("/v1/settings", changes); data.settings = r.settings; msg.textContent = "Saved"; return true; } catch (e) { msg.textContent = "Not saved: " + e.message; return false; } };
    apply.onclick = save; ok.onclick = async () => { if (await save()) closeMenus(); };
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    $("#w-search").onclick = palette; $("#w-search").onkeydown = (e) => { if (e.key === "Enter") palette(); };
    $("#w-settings").onclick = settings; $("#w-step-add").onclick = recordStep;
    $("#w-theme").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    $("#w-agents").onclick = () => openTab({ id: "setup", title: "Connect an agent", icon: "plug" });
    $("#right-close").onclick = () => { S.rightOpen = false; saveUI(); renderAll(); };
    $("#w-project").onclick = (e) => menu(e.currentTarget, [{ header: "Tracked projects" }, ...S.projects.map((p) => ({ label: p.name, meta: p.root, icon: p.key === S.key ? "check" : "folder", run: () => { S.key = p.key; S.step = "live"; S.tabs = []; S.active = "overview"; S.sel = null; S.view = {}; saveUI(); load(true); } })), "-", { label: "Track another folder…", icon: "plus", run: () => openTab({ id: "setup", title: "Connect an agent", icon: "plug" }) }]);
    $("#w-step").onclick = (e) => { if (!S.st) return; menu(e.currentTarget, [{ label: "Live (latest)", meta: `${S.st.pending.length} pending`, icon: S.step === "live" ? "check" : "history", run: () => setStep("live") }, "-", ...[...S.st.steps].reverse().slice(0, 30).map((s) => ({ label: `#${s.n} ${s.title.slice(0, 48)}`, meta: ago(s.ts), icon: S.step === s.n ? "check" : "flag", run: () => setStep(s.n) }))]); };
    let lastShift = 0;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Shift" && !e.repeat) { const now = Date.now(); if (now - lastShift < 350) palette(); lastShift = now; }
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "p")) { e.preventDefault(); palette(); }
      if ((e.ctrlKey || e.metaKey) && e.key === ",") { e.preventDefault(); settings(); }
      if (e.key === "Escape") closeMenus();
      if (e.altKey && /^[1-9]$/.test(e.key)) { const t = FIXED[+e.key - 1]; if (t) openTab(t); }
    });
    document.querySelectorAll(".resize").forEach((h) => h.addEventListener("pointerdown", (e) => {
      const key = h.dataset.r, start = { x: e.clientX, y: e.clientY, v: store.get(key, key === "bh" ? 220 : key === "lw" ? 280 : 320) }; h.setPointerCapture(e.pointerId);
      const mv = (ev) => { const d = key === "lw" ? ev.clientX - start.x : key === "rw" ? start.x - ev.clientX : start.y - ev.clientY; const v = Math.max(160, Math.min(key === "bh" ? 600 : 640, start.v + d)); store.set(key, v); key === "bh" ? $("#bottom").style.setProperty("--bh", v + "px") : $("#ide").style.setProperty("--" + key, v + "px"); };
      const up = () => { h.removeEventListener("pointermove", mv); h.removeEventListener("pointerup", up); for (const k of Object.keys(S.view)) if (S.view[k]) S.view[k].fit = true; };
      h.addEventListener("pointermove", mv); h.addEventListener("pointerup", up);
    }));
  }

  boot();
})();
