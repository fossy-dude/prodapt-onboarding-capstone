/caveman

## Testing

Integration and slow tests **skip by default** in both Python projects
(`service_webapp`, `cdr-pipeline`). Plain `pytest` (and `just test` /
`just test-cdr`) runs unit tests only — integration/slow tests are marked
`skip`, not run.

Opt in explicitly with either flag (they combine):

- `pytest --run-integration` — run integration tests
- `pytest --run-slow` — run slow tests
- Integration tests are marked both `slow` + `integration`, so either flag runs them.

Through tox / just (flags forward via `--`):

- `just test-integration` / `just test-cdr-integration`
- slow: `cd service_webapp && uvx --with tox-uv tox -e test -- --run-slow`

Mechanism: `pytest_addoption` + `pytest_collection_modifyitems` in each project's
`tests/conftest.py`; markers `slow` and `integration` are registered in
`[tool.pytest.ini_options]`. **Do not reintroduce `pytest -m "not slow"`** — the
conftest hook is the single source of truth (the `-m not slow` was removed from
both tox `[tool.tox.env.test]` commands for this reason).
