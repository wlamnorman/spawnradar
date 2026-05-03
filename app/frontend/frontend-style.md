# Frontend Guide

This document describes how SpawnRadar frontend code is organized and how new
frontend work should be added. Keep it current when frontend structure,
shared components or conventions change.

## Goals

- Reuse shared template partials and shared JS modules before adding page-local
  copies.
- Keep product UI quieter than the marketing home page.
- Prefer server-rendered HTML with small focused JavaScript enhancements.
- Avoid duplicate implementations of the same component across Jinja and JS.

## Current Structure

- `app/frontend/templates/base.html`
  Shared shell, navbar, footer, metadata and script/style entry points.
- `app/frontend/templates/partials/`
  Shared template fragments.
  Current shared fragments include the game info form and tag catalogs.
- `app/frontend/templates/`
  Page templates grouped by area (`auth/`, `games/`, `billing/`, `marketing/`,
  `legal/`).
- `app/frontend/static/style.css`
  Shared stylesheet and design tokens.
- `app/frontend/static/game-form.js`
  Shared game-form enhancements: char counters and tag pickers.
- `app/frontend/static/confirm.js`
  Shared confirm-dialog behavior for destructive actions.

## Shared First

When adding or changing frontend UI:

- If markup appears on more than one page, extract a partial in
  `app/frontend/templates/partials/`.
- If the same interactive behavior appears on more than one page, move it into
  `app/frontend/static/` instead of copying inline scripts.
- If an API-driven UI needs to render the same component as the initial page,
  keep one shared HTML implementation and reuse it from both the page and the
  API response path.

Current examples:

- The game create and game settings pages share
  `partials/game_info_form.html` and `static/game-form.js`.

## Styling Rules

- Shared tokens live in `:root` in
  [style.css](/Users/wlam/code/SpawnRadar/app/frontend/static/style.css).
- Add named CSS variables before introducing new one-off color values.
- Reuse existing shared classes for cards, buttons, alerts, pills and form
  controls before inventing page-specific variants.
- Avoid inline styles in templates unless there is a very strong reason.
- Prefer product surfaces to stay neutral and restrained; keep hero-specific
  palettes for marketing moments.

## Template Rules

- Prefer `data-*` hooks over inline `onclick` handlers.
- Keep page templates mostly declarative: structure, content and component
  composition.
- Push repeated HTML into partials instead of duplicating blocks across pages.
- If a template needs page-specific behavior, load a static script for that
  page or shared module rather than embedding large inline scripts.

## JavaScript Rules

- Keep JS small and page-scoped unless it is genuinely shared.
- Prefer DOM enhancement over client-side re-rendering.
- If server-rendered components are later inserted dynamically, reuse the same
  HTML structure from the server instead of rebuilding the component separately
  in JS.
- Use event delegation for repeated controls when it simplifies page code.

## When To Update This Document

Update this file when any of the following changes:

- frontend folder structure
- shared partial inventory
- shared JS module inventory
- major frontend conventions
- how duplicated frontend components are shared between server rendering and
  dynamic updates
