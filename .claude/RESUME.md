# Resume notes (agents may be cut off by usage limits)

State is on disk and on the remote. Run `.claude/snapshot.sh` any time: it saves each agent worktree (committed +
uncommitted + untracked) to refs/snapshots/<agent> and pushes it to origin as `snapshot/<agent>`.
To continue a cut-off task: start an agent in that worktree (path below) and tell it to `git diff HEAD` / read
its task, finish, run `python -m pytest -q` (use `uv run --with pytest python -m pytest -q` if pytest is missing),
commit ONE plain single-line message with no co-author, then merge branch into main and push.
If a worktree is gone: `git checkout -b <name> origin/snapshot/<agent>` restores everything.

Rules for every task: zero runtime deps, Python >=3.10, tests in tests/, single-line commits, NO Co-Authored-By,
do not edit docs/COMMANDS.md / CHANGELOG.md in the branch (maintainer writes docs at merge), never commit Kairos
fixtures, never run heavy commands in ~/projects/kairos (archive: ~/kairos-archive/mapwright/).

| Agent id | Task | Branch | Files it owns | Status |
|---|---|---|---|---|
| af88e89863cffbf2b | Item 1 first-run auth UX + UI alignment | worktree-agent-af88e89863cffbf2b | ui/*, tests/test_ui_auth.py | MERGED |
| a5d65fb6ae1681d5e | Item 6 disconnect removes empty files | worktree-agent-a5d65fb6ae1681d5e | connect.py (uninstall), tests/test_disconnect.py | MERGED |
| a3f2cce87296030bd | Item 2 `init --local/--home`, MAPWRIGHT_HOME in MCP env + hook commands, home discovery via .mapwright/home.json, /v1/ping home field | worktree-agent-a3f2cce87296030bd | config.py, connect.py (install/snippet), cli.py (init/connect/open/up), hooks.py (home), server.py (ping), tests/test_local_home.py | MERGED |
| aa336b3f47bc409db | Item 3 ignore: .gitignore + globs (new ignore.py), `respect_gitignore`, no global mutation in scan, max_files warning/truncated_info, init suggestions + `--apply-ignore` | worktree-agent-aa336b3f47bc409db | ignore.py, config.py (DEFAULTS/validation), analyze.py (scan), track.py (refresh/state), cli.py (init/doctor), tests/test_ignore.py | MERGED |
| a69e2643825a5e86a | Item 4 react-router route tables, Firestore rules/collections as data source, zod/components, Kairos gap findings | worktree-agent-a69e2643825a5e86a | routes_js.py, firestore.py (new), analyze.py hooks, render.py/brief.py, tests/test_routes_js.py, tests/test_firestore.py | MERGED |
| aa6fcf58946b5486b | Item 5 clean auto-step titles (titles.py), subagent-safe auto_step=turn, noise/lockfile exclusion (noise.py), hook payload hygiene | worktree-agent-aa6fcf58946b5486b | hooks.py, track.py (record/step), titles.py, noise.py, tests/test_titles.py, tests/test_autostep.py | MERGED |

After all merge: write docs/COMMANDS.md + CHANGELOG.md + README limits, update docs/ROADMAP.md statuses, push.
Then phase 2 (web: origin allowlist/CORS in server.py, Cloudflare Pages deploy) and phase 3 (deb/macOS) per docs/ROADMAP.md.
