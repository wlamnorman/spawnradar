# Frontend Style Guide

SpawnRadar's default visual direction comes from the public home page:

- dark editorial hero sections
- bright violet brand accents
- cool slate neutrals for surfaces, borders, and supporting text
- simple white cards with restrained borders instead of heavy shadows

## Design Tokens

The shared color tokens live in [frontend/static/style.css](/Users/wlam/code/SpawnRadar/frontend/static/style.css#L5) under `:root`.

Use these first before adding any new hex values:

- `--color-brand`, `--color-brand-hover`: primary actions and brand links
- `--color-bg-page`, `--color-bg-surface`, `--color-bg-muted`: page, card, and muted backgrounds
- `--color-border`: default border color for cards, inputs, and dividers
- `--color-text`, `--color-text-soft`, `--color-text-muted`, `--color-text-faint`: text hierarchy
- `--color-hero-*`: hero-only palette for dark marketing sections

## Styling Rules

- Prefer white or muted slate surfaces for product UI.
- Prefer the violet brand color for primary buttons, links, and key emphasis.
- Use the dark `--color-hero-*` palette for major marketing moments only.
- Keep borders subtle and rely on spacing and typography before adding strong shadows.
- Reuse existing card/button/nav styles before creating page-specific variants.

## Copy And Layout Tone

- Marketing sections should feel sharp and editorial, not playful or loud.
- Product UI should stay quieter than the home page: neutral surfaces, clear spacing, compact actions.
- Use short, direct headings and supporting text that explains workflow or outcome.

## Implementation Notes

- If a new page needs a new custom color, add a named CSS variable first.
- If a component is likely to appear on more than one page, style it as a shared class in `frontend/static/style.css`.
- Avoid one-off inline colors in templates.
