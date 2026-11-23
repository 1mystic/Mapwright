# Contributing to Mapwright

Thanks for helping. Mapwright is small on purpose; keep changes focused.

## Dev setup

```bash
git clone https://github.com/1mystic/Mapwright && cd Mapwright
uv sync            # or: python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```

## Tests and lint

```bash
uv run --with pytest python -m pytest -q
uv run --python 3.10 --with pytest python -m pytest -q   # the oldest supported Python
uvx ruff check src tests scripts
```

CI is manual only (Actions, "tests", Run workflow); run the suite locally before you open a PR, on 3.10 and a current Python.

## Rules

- Zero runtime dependencies. The package uses the standard library only; `pyyaml` stays an optional extra. Do not add to `dependencies`.
- Python 3.10 compatible syntax and stdlib.
- Match the existing compact style; do not reformat code you are not changing.
- Add a test for behaviour you add or fix.
- Commit messages are a single plain line, for example `Fix gitignore handling for nested folders`.

## Dogfooding

Track Mapwright with itself, keeping history inside the checkout (git-ignored):

```bash
mapwright init --local --connect claude-code
mapwright open
```
