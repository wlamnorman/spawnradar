# Game Import

This subsystem turns an external game URL into a reviewable draft that can
pre-fill SpawnRadar's game setup flow.

The parsing and mapping logic remains intentionally isolated from persistence
and route code. The goal is to keep imports deterministic, testable and safe
to evolve even though the resulting draft is now wired into the game setup UI.

## Design Goals

- Treat Steam as one adapter, not as a special-case feature.
- Keep extraction separate from interpretation.
- Never auto-save a customer game from imported data.
- Leave a clean seam for future enrichment, including possible LLM use.

## File Map

- `models.py`
  Defines the core data structures shared by the subsystem:
  `ImportedGameSourceData`, `ImportedGameDraft` and `ImportedGamePreview`.

- `registry.py`
  Defines the adapter protocol, a decorator-based self-registry and helper
  functions for matching a URL to a registered adapter.

- `steam.py`
  Implements the first concrete adapter. It fetches Steam app details,
  extracts deterministic metadata and returns both raw source data and the
  normalized draft.

- `steam_tag_mapping.py`
  Maps a conservative subset of high-confidence Steam metadata into
  SpawnRadar's existing setup taxonomy. It prefers official Steam API genres
  and categories, then adds only a small allowlist of stable store-tag
  mappings for themes and curated keywords.

- `service.py`
  Orchestrates adapter loading and URL import. This is the entrypoint that
  future application code should call.

- `__init__.py`
  Re-exports the public surface for convenient imports elsewhere.

## Interaction Flow

1. A caller creates `GameImportService`.
2. `GameImportService.import_url(url)` ensures built-in adapters are loaded.
3. The service asks the registry for an adapter that can handle the URL.
4. The adapter fetches raw source data and normalizes it into a draft.
5. The Steam adapter also maps a conservative subset of source metadata into
   SpawnRadar setup fields when the mapping is high confidence.
6. The service returns an `ImportedGamePreview` containing both:
   - raw source data from the external system
   - a normalized draft suitable for pre-filling a setup form

## Why The Preview Contains Two Layers

`ImportedGameSourceData` is the extraction layer. It answers "what did Steam
actually say?"

`ImportedGameDraft` is the interpretation layer. It answers "what would we
prefill in our setup form, including any stable mapped tags?"

The current Steam mapping intentionally uses trust tiers:
- official Steam API genres first
- official Steam API categories for game-mode mapping
- only a small allowlist of stable store tags after that

The mapper also caps autofill so imports do not try to fully decide the setup
for the user.

That separation matters because import data should remain inspectable even if
the draft-mapping logic changes later.

## Future Extensions

- Add more adapters in this same directory, for example `itch_io.py` or
  `epic.py`.
- Add an optional draft enhancer that can summarize or refine imported text.
- Add more deterministic mappings only when the source tags are stable enough
  to line up cleanly with SpawnRadar taxonomy.
