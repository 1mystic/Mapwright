# Setup and deploy guide

This guide covers four things, in the order you will need them:

1. [Install Mapwright on your machine](#1-install) (the tool itself, 2 minutes)
2. [Connect your coding agent](#2-connect-your-agent) (Claude Code, Cursor, VS Code, Windsurf, Gemini, Codex, opencode, others)
3. [Add the editor extension](#3-editor-extension-optional) (optional)
4. [Publish the website and the packages for free](#4-deploy-plan-free-tier) (only if you want to share Mapwright with others)

The short version of the deploy plan: **the MCP server and the map run on each developer's own
machine; only the website (and, optionally, the packages) need hosting, and all of it fits in free tiers.**

---

## 1. Install

Requirements: Python 3.10 or newer. Nothing else: Mapwright has no runtime dependencies.

```bash
pipx install ./mapwright-0.1.0          # from the unzipped folder
```

or, without pipx:

```bash
pip install ./mapwright-0.1.0
```

Once it is published to PyPI (see section 4) this becomes `pipx install mapwright`.

Check it works:

```bash
mapwright --version
```

```bash
mapwright guide
```

Optional: `pip install pyyaml` makes Docker Compose and Kubernetes parsing more complete. Without it a small built-in parser handles common files.

### Track a project

```bash
cd your-project
mapwright init
```

This records the current state as **step 0 (baseline)**. History is stored outside the project, in
`~/.mapwright/projects/<project>/`. Nothing is written into your repository unless you connect an agent
or ask for notes in `AGENTS.md`.

### Open the map

```bash
mapwright open
```

This starts the local daemon (`http://127.0.0.1:7979`) if it is not running and opens the browser. The
link carries a local token; don't share it. Stop the daemon with `mapwright down`.

---

## 2. Connect your agent

See what is installed and what is connected:

```bash
mapwright connect --list
```

Connect one (project scope writes into the project; `--scope user` connects it for every project):

```bash
mapwright connect claude-code
```

Restart the agent, or start a new session, so it loads the MCP server.

| Agent | What `connect` writes | Automatic steps at turn end |
|---|---|---|
| **Claude Code** | `.mcp.json` + hooks in `.claude/settings.local.json` (user scope: `claude mcp add -s user` + `~/.claude/settings.json`) | yes (hooks) |
| **Cursor** | `.cursor/mcp.json` (user: `~/.cursor/mcp.json`) | no: the agent calls `step` |
| **VS Code (Copilot agent mode)** | `.vscode/mcp.json` (user: your VS Code `mcp.json`) | no |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` | no |
| **opencode** | `opencode.json` → `mcp.mapwright`; for automatic steps also copy `integrations/opencode/mapwright.js` into `.opencode/plugin/` | yes (plugin) |
| **Codex CLI** | `~/.codex/config.toml` → `[mcp_servers.mapwright]` | no |
| **Gemini CLI** | `.gemini/settings.json` (user: `~/.gemini/settings.json`) | no |
| **Claude Desktop** | `claude_desktop_config.json` | no |
| **Cline, Roo Code, Zed, JetBrains AI** | print the config and paste it in the tool's MCP settings: `mapwright connect --print cline` | no |
| **Anything else** | nothing: run `mapwright watch` in the project and steps close after a quiet period | quiet period |

Existing config files are merged, never replaced. A copy of each file is saved in `~/.mapwright/backups/`
before it is changed. A file that is not plain JSON (for example with comments) is left alone, and you are
told to paste the snippet yourself.

### Claude Code plugin (alternative to `connect`)

The repository root contains a plugin marketplace. In Claude Code:

```
/plugin marketplace add <path-or-github-repo-of-mapwright>
/plugin install mapwright
```

The plugin brings the MCP server, the hooks and the skill. It needs `mapwright` on your PATH.

### Tell the agent (optional)

The MCP server already sends short instructions. If you want them in your instructions file too:

```bash
mapwright agents-md --file CLAUDE.md
```

(`AGENTS.md`, `GEMINI.md` and `.cursorrules` work the same way.) For agents that read **Agent Skills**,
copy `integrations/skills/mapwright/` into the agent's skills folder (for Claude Code: `.claude/skills/`).
The skill also explains the shell fallback (`mapwright brief`, `mapwright step …`) for agents without MCP.

### Check

```bash
mapwright doctor
```

The **Connect** panel in the UI shows the same, with buttons to connect and disconnect.

---

## 3. Editor extension (optional)

For VS Code, Cursor, Windsurf and VSCodium:

```bash
code --install-extension integrations/vscode/mapwright-vscode-0.1.0.vsix
```

(Cursor: `cursor --install-extension …`; or drag the `.vsix` onto the Extensions view.)

It adds **Mapwright: Open Map** (beside your code), **Record Step**, **Copy Agent Brief**, **Connect an
Agent**, and a status bar item with the current step, pending changes, open todos and unverified claims. On
VS Code 1.101 and later it also offers the MCP server to Copilot directly.

JetBrains IDEs: there is no plugin yet. Open the map URL in the IDE's built-in browser (or a window beside
the IDE); the UI follows the same New UI look.

---

## 4. Deploy plan (free tier)

### What runs where

```
 developer's machine                                    public internet (free hosting)
 ───────────────────────────────────────────            ────────────────────────────────
 coding agent ──stdio──▶ mapwright mcp                   website: landing, docs, setup,
      │                     │                            live demo (static files only)
      └─hooks──▶ mapwright hook                                  ▲
                            ▼                                    │ pipx install mapwright  ◀── PyPI
            ~/.mapwright (steps, file versions)                  │ VS Code extension       ◀── Marketplace / Open VSX
                            ▼                                    │ Claude Code plugin      ◀── GitHub repo
            mapwright daemon → UI on 127.0.0.1
```

**The MCP server must run locally.** It reads the project's files as the agent changes them and keeps
their history. A hosted MCP server could only do that if every developer uploaded their code to it, which
defeats the privacy model and adds latency to every tool call. So there is nothing to host for the
MCP server: each user's agent starts `mapwright mcp` itself.

What you do host: **the website** (static files: HTML, CSS, JS, the demo data) and **the packages**.

### Website hosting: options compared

The site is about 5 MB of static files (the diagram renderer is about 3.3 MB of that). Any static host works.
Free-tier limits change; check the provider's pricing page before you rely on a number below.

| Host | Free tier (check current terms) | Good | Watch out for | Verdict |
|---|---|---|---|---|
| **Cloudflare Pages** | Static requests and bandwidth not metered on the free plan; a monthly build allowance; custom domain + HTTPS | Fast global CDN; no bandwidth worries if the demo gets popular; deploy from Git or CLI | Build minutes are limited (this site needs no build on their side if you upload `web/`) | **Recommended** |
| **GitHub Pages** | Free for public repositories; soft limits on site size (about 1 GB) and monthly bandwidth (about 100 GB) | Zero extra accounts if the code is on GitHub; workflow included | Public repo needed on the free plan; soft bandwidth cap | **Easiest** if the repo is public |
| **Firebase Hosting** (Spark, no-cost) | Storage and data transfer quotas on the no-cost plan (on the order of 10 GB each); custom domain + HTTPS | Solid CDN; good if you already use Firebase or Google Cloud; `firebase.json` included | Transfer quota is the tightest of the three for a 5 MB demo page: roughly a few thousand full demo visits a month before you need the Blaze plan | Good choice, especially inside a Firebase project |
| Netlify (free) | Credit-based free plan | Easy previews per branch | Credits are shared across bandwidth, builds and functions | Fine alternative |
| Vercel (Hobby) | Free for personal, non-commercial use | Great previews | Hobby terms exclude commercial use | Only for a personal project |

**Recommendation:** Cloudflare Pages for the public site, because static traffic is not metered on the free plan
and the demo page is heavy. Use GitHub Pages if you want everything in one place and the repository is
public. Firebase Hosting works well too, with the included config, and is the natural pick if the rest
of your stack is on Firebase. All three give you HTTPS and a custom domain for free.

### Build the site

```bash
python scripts/build_site.py
```

This copies the UI into `web/app/` and records a full demo bundle (`web/app/demo.json`) from the scripted
agent session, so the live demo works with no server. The output folder to publish is `web/`.

### Deploy: Cloudflare Pages

Dashboard: **Workers & Pages → Create → Pages → Upload assets**, drop the `web/` folder. Or with the CLI:

```bash
npx wrangler pages deploy web --project-name mapwright
```

To deploy from Git instead: connect the repository, set the build command to `python scripts/build_site.py`
and the output directory to `web`.

### Deploy: GitHub Pages

`.github/workflows/pages.yml` is included. Push to `main`, then in the repository **Settings → Pages →
Source: GitHub Actions**. The workflow builds the site and the demo and publishes `web/`.

### Deploy: Firebase Hosting

`firebase.json` is included (it serves `web/`, with long cache lifetimes for the renderer and short ones for HTML).

```bash
npm install -g firebase-tools
```

```bash
firebase login
```

```bash
cp .firebaserc.example .firebaserc        # put your Firebase project id in it
```

```bash
python scripts/build_site.py && firebase deploy --only hosting
```

### Publish the packages (all free)

| What | Where | How |
|---|---|---|
| Python package | **PyPI** | `python -m build` then `twine upload dist/*` (create a PyPI account and an API token first). Users then run `pipx install mapwright`. |
| VS Code extension | **VS Code Marketplace** and **Open VSX** (Cursor, Windsurf and VSCodium use Open VSX) | Change `publisher` in `integrations/vscode/package.json` to your publisher id, then `npx @vscode/vsce publish` and `npx ovsx publish`. |
| Claude Code plugin | **your GitHub repository** | The root `.claude-plugin/marketplace.json` makes the repo a marketplace: `/plugin marketplace add <owner>/<repo>`. |
| MCP server listing | MCP directories (for example the official MCP Registry) | List it as a local stdio server started with `mapwright mcp`. |

### If you later want a shared, hosted map (not built yet)

For teams that want to browse a map without running Mapwright, the path that keeps code private is to
publish an **export** rather than the code: `mapwright export -o map/` writes `MAP.md` (renders on GitHub)
plus every diagram and the step history as plain files. Commit that, or upload it to any of the static
hosts above. A hosted, read-only MCP server that serves an uploaded export would fit a free serverless tier
(Cloudflare Workers, Google Cloud Run or Firebase Functions); it is a possible future addition, not part
of this release.

---

## Stop, disconnect, remove

```bash
mapwright down                              # stop the daemon
```

```bash
mapwright disconnect claude-code            # remove the MCP entry and hooks (add --scope user if you used it)
```

```bash
pipx uninstall mapwright
```

```bash
rm -rf ~/.mapwright                         # delete all tracked history
```
