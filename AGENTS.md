# AGENTS.md

Guidance for coding agents working in this repository.

## Required checks

- Before finishing broad Python changes, run `make typecheck`.
- For narrower Python changes, run `.venv/bin/basedpyright` on the affected files at minimum.
- Run relevant tests for the area you changed.
- Fix type errors rather than suppressing them unless there is a concrete reason.

## Standard commands

```bash
make lint
make typecheck
make test
make check
```

## Design documents

Some subsystems have a `DESIGN.md` that explains the intent and structure of that
area at a conceptual level. Keep these current when making architectural changes:
new dimensions, renamed concepts, restructured data models, or changes to how data
flows between subsystems.

Do not update design docs for small implementation details such as numeric tuning,
small helper refactors, or minor internal renames. These documents should describe
how the system is meant to work, not every changing detail.

Current design documents:
- `app/creator_index/DESIGN.md`

## Stable repository facts

- `customer_games` are the customer-owned games tracked in SpawnRadar.
- `app/creator_index/` is the background-built platform data bank for reusable creator/account data.
- The durable primitive in the creator index is a platform account in `source_accounts`, not a merged cross-platform creator identity.
- `creator_games_played` is the aggregated record of games a platform account has been observed playing.
- `creator_index` and customer-facing prospect/review flows are related, but they are not the same subsystem and should not be conflated in code structure.

## Notes

- `make run` keeps the existing local DB and seed dev data in place.
