# Contributing

Thanks for helping. A few ground rules keep this small project easy to maintain.

## Before you start

- Open an issue first for a new converter or a new input format, so we can agree on scope
  and output shape before code is written.
- Bug fixes and mapping improvements to an existing converter can go straight to a pull
  request.

## Working on the code

```sh
uv sync --all-extras
uv run ruff check . && uv run pytest
```

Both must pass. `ruff format --check .` runs in CI too; `uv run ruff format .` fixes
formatting.

## Tests and fixtures

- Add a fixture for every new mapping. If the existing fixtures do not contain the
  construct you are mapping, extend `tests/fixtures/handwritten/mychart_like_ccd.xml` or add
  a new hand-written file next to it.
- Synthetic data only. Never commit a real record, even a redacted one. Synthea output and
  hand-written documents with made-up names, identifiers and values are fine. Say where a
  fixture came from in `tests/fixtures/README.md`.
- Assert specific values, not just counts, for anything you map.

## Style

Type hints everywhere, small modules, docstrings where the behaviour is not obvious from the
code. Keep the runtime dependency list at `lxml` only unless the issue discussion agreed
otherwise.
