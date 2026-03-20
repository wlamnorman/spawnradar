# AGENTS.md

Guidance for coding agents working in this repository.

## Required Checks

- Before finishing Python changes, run `make typecheck` if the change is broad.
- For narrower Python changes, run `.venv/bin/basedpyright` on the affected files at minimum.
- Fix type errors rather than suppressing them unless there is a concrete reason.
- Run relevant tests for the area you changed. For broad changes, run `.venv/bin/pytest`.

## Standard Commands

```bash
make lint
make typecheck
make test
make check
```

## Notes

- `make run` and `make dev` keep the existing local DB and seed dev data in place.
- Use `sp rm-db` when you want a clean local reset.
