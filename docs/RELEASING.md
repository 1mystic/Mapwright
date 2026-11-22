# Releasing to PyPI

The PyPI name `mapwright` belongs to an unrelated project, so Mapwright is published as **`mapwright-agent`**.
The command is still `mapwright` and the Python package is still `mapwright`:

```bash
pipx install mapwright-agent
mapwright --version
```

Do not install it into the same environment as the other `mapwright` package (pipx keeps them apart).

## One-time setup (no API token needed: PyPI trusted publishing)

1. Create accounts at pypi.org (and test.pypi.org to rehearse) and turn on 2FA.
2. On PyPI go to *Your account → Publishing → Add a new pending publisher* and enter:
   project `mapwright-agent`, owner `1mystic`, repository `Mapwright`, workflow `release.yml`, environment `pypi`.
   (Same on test.pypi.org with environment `testpypi`.)
3. On GitHub: *Settings → Environments*: create `pypi` (add yourself as required reviewer if you want a manual approval before each release) and `testpypi`.

## Each release

1. Bump `__version__` in `src/mapwright/__init__.py` (the only place; `pyproject.toml` reads it), move the
   `CHANGELOG.md` "Unreleased" notes under the new version, commit, push.
2. Rehearse (optional): *Actions → release → Run workflow → testpypi*, then
   `pipx install --index-url https://test.pypi.org/simple/ mapwright-agent`.
3. Publish: `git tag v0.1.0 && git push origin v0.1.0`. The workflow checks the tag matches the version, runs the
   tests, builds, publishes to PyPI and creates a GitHub release with the files attached.
