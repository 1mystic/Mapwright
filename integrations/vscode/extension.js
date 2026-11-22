// Mapwright for VS Code (and Cursor, Windsurf, VSCodium). Plain JavaScript, no build step.
// It runs the `mapwright` CLI; the map itself is served by the local Mapwright daemon.
const vscode = require("vscode")
const { execFile } = require("child_process")

function cfg() { return vscode.workspace.getConfiguration("mapwright") }
function folder() { return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath }

function run(args, opts = {}) {
  const parts = cfg().get("command", "mapwright").trim().split(/\s+/)
  return new Promise((resolve, reject) => {
    execFile(parts[0], [...parts.slice(1), ...args], { cwd: opts.cwd || folder(), timeout: opts.timeout || 60000, maxBuffer: 8 * 1024 * 1024 },
      (err, stdout, stderr) => err ? reject(new Error((stderr || err.message).trim())) : resolve(stdout))
  })
}

function missing(e) {
  vscode.window.showErrorMessage(`Mapwright: ${e.message}. Install it with \`pipx install mapwright\` (or set "mapwright.command").`, "Settings")
    .then((c) => c && vscode.commands.executeCommand("workbench.action.openSettings", "mapwright.command"))
}

let panel
async function openMap(external) {
  if (!folder()) return vscode.window.showWarningMessage("Mapwright: open a folder first.")
  let info
  try { info = JSON.parse(await run(["open", "--json"])) } catch (e) { return missing(e) }
  const uri = await vscode.env.asExternalUri(vscode.Uri.parse(info.url))
  if (external || cfg().get("openIn") === "browser") return vscode.env.openExternal(uri)
  if (panel) { panel.reveal(vscode.ViewColumn.Beside); return }
  panel = vscode.window.createWebviewPanel("mapwright", "Mapwright", vscode.ViewColumn.Beside, { enableScripts: true, retainContextWhenHidden: true })
  const src = uri.toString(true)
  const origin = `${uri.scheme}://${uri.authority}`
  panel.webview.html = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src ${origin}; style-src 'unsafe-inline'">
<style>html,body,iframe{margin:0;padding:0;border:0;width:100%;height:100%;overflow:hidden;background:#1e1f22}</style></head>
<body><iframe src="${src}" allow="clipboard-write"></iframe></body></html>`
  panel.onDidDispose(() => { panel = undefined })
}

let item
async function refreshStatus() {
  if (!item || !cfg().get("statusBar") || !folder()) { item?.hide(); return }
  try {
    const s = JSON.parse(await run(["status", "--json"], { timeout: 20000 }))
    item.text = `$(type-hierarchy) step ${Math.max(0, s.steps - 1)}` + (s.pending ? ` · ${s.pending} changed` : "") + (s.open_todos ? ` · ${s.open_todos} todo` : "") + (s.problems ? ` · $(warning) ${s.problems}` : "")
    item.tooltip = `Mapwright: ${s.counts.modules} modules, ${s.counts.functions} functions, ${s.counts.tables} tables. Click to open the map.`
    item.show()
  } catch { item.text = "$(type-hierarchy) Mapwright"; item.tooltip = "Mapwright is not tracking this folder yet. Click to open."; item.show() }
}

function activate(context) {
  const reg = (id, fn) => context.subscriptions.push(vscode.commands.registerCommand(id, fn))
  reg("mapwright.open", () => openMap(false))
  reg("mapwright.openExternal", () => openMap(true))
  reg("mapwright.init", async () => { try { vscode.window.showInformationMessage((await run(["init"])).split("\n")[0]); refreshStatus() } catch (e) { missing(e) } })
  reg("mapwright.step", async () => {
    const title = await vscode.window.showInputBox({ prompt: "What was done? (the changed files are computed)", placeHolder: "Add refunds to checkout" })
    if (!title) return
    try { vscode.window.showInformationMessage("Mapwright: " + (await run(["step", title])).trim()); refreshStatus() } catch (e) { missing(e) }
  })
  reg("mapwright.brief", async () => { try { const b = await run(["brief"]); await vscode.env.clipboard.writeText(b); vscode.window.showInformationMessage(`Mapwright: brief copied (${b.length} characters, about ${Math.round(b.length / 4)} tokens).`) } catch (e) { missing(e) } })
  reg("mapwright.connect", async () => {
    const pick = await vscode.window.showQuickPick([
      { label: "VS Code (Copilot agent mode)", id: "vscode" }, { label: "Claude Code", id: "claude-code" }, { label: "Cursor", id: "cursor" },
      { label: "Windsurf", id: "windsurf", scope: "user" }, { label: "opencode", id: "opencode" }, { label: "Codex CLI", id: "codex", scope: "user" }, { label: "Gemini CLI", id: "gemini" },
    ], { placeHolder: "Which agent should use Mapwright in this project?" })
    if (!pick) return
    try { vscode.window.showInformationMessage("Mapwright: " + (await run(["connect", pick.id, "--scope", pick.scope || "project"])).split("\n")[0]) } catch (e) { missing(e) }
  })
  item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50)
  item.command = "mapwright.open"
  context.subscriptions.push(item)
  refreshStatus()
  const timer = setInterval(refreshStatus, 15000)
  context.subscriptions.push({ dispose: () => clearInterval(timer) })
  context.subscriptions.push(vscode.workspace.onDidSaveTextDocument(() => setTimeout(refreshStatus, 1500)))

  // VS Code 1.101+: offer the MCP server to Copilot agent mode without editing mcp.json
  if (vscode.lm && typeof vscode.lm.registerMcpServerDefinitionProvider === "function" && vscode.McpStdioServerDefinition) {
    context.subscriptions.push(vscode.lm.registerMcpServerDefinitionProvider("mapwright", {
      provideMcpServerDefinitions: async () => {
        if (!folder()) return []
        const parts = cfg().get("command", "mapwright").trim().split(/\s+/)
        return [new vscode.McpStdioServerDefinition("Mapwright", parts[0], [...parts.slice(1), "mcp"], { MAPWRIGHT_ROOT: folder() })]
      },
    }))
  }
}

function deactivate() {}
module.exports = { activate, deactivate }
