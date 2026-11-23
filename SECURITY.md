# Security

## Model

- Mapwright is local-first. The daemon (`mapwright up`) binds to `127.0.0.1` only and nothing is sent to any remote service.
- Every API call needs the bearer token stored in `<home>/token` (mode 0600, home is `~/.mapwright` or a project-local `.mapwright`). `mapwright token` shows where it lives, `mapwright token --rotate` replaces it.
- Browser access is limited to an origin allowlist: the daemon's own origin plus the exact origins in the `web_origins` setting (default `https://mapwright.pages.dev`). The token is still required.
- Secrets in tracked files are redacted before they are stored (`redact` setting).
- `mapwright forget --purge` deletes a project's stored history.

## Reporting a vulnerability

Please report privately through GitHub: Security tab, "Report a vulnerability" (private security advisories) on https://github.com/1mystic/Mapwright. Do not open a public issue. Include the version (`mapwright --version`), steps to reproduce and the impact. You can expect an acknowledgement within a few days.
