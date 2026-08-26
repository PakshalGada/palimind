---
name: palimind-testing
description: >
  How to run and write tests for Palimind (pytest, Vitest, Playwright) and
  what CI expects. Use when adding tests, fixing bugs, or verifying changes.
  Triggers: test, pytest, coverage, CI, quality gate.
---

# Testing Palimind

## Backend (pytest)

```
cd packages/backend
python -m pytest -m "not integration"   # fast unit suite (CI default)
python -m pytest                        # everything (integration needs Ollama)
```

- Tests live in `packages/backend/tests/`.
- Mark anything needing a live backend/Ollama with `@pytest.mark.integration`.
- Unit-test targets of highest value: tools registry, chunkers, config,
  memory, settings parsing.

## Frontend

```
npm run lint  --prefix packages/frontend   # oxlint
npm run build --prefix packages/frontend   # tsc -b catches type errors
```

## Full gates before opening a PR

```
make lint            # ruff + oxlint
make check-imports   # no legacy 'core' package references
make test            # backend pytest + frontend build/lint
ruff format --check .  (in packages/backend)
```

CI mirrors these gates on Linux/macOS/Windows — run them locally first.
