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

## Design documents

Some subsystems have a `DESIGN.md` that explains the intent and structure of
that area at a conceptual level. Keep these current when making architectural
changes — new dimensions, renamed concepts, restructured data models, changes
to how data flows between subsystems.

Do **not** update them for small implementation details: tweaking a numeric
weight, adding an alias, extending a catalog, or renaming an internal helper.
These documents describe *how the system is meant to work*, not every parameter
value. A reader should be able to understand the design from the document
without it becoming a maintenance burden.

Current design documents:
- `app/games/tags/DESIGN.md` — tag taxonomy, profiles, normalization, query composition

## Notes

- `make run` keep the existing local DB and seed dev data in place.
- Use `sr rm-db` when you want a clean local reset.
