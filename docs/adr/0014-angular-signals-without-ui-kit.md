# 14. Build the frontend with Angular signals and no UI kit

- **Status:** accepted, November 2026

## Context

The design is specific to this product, and a component library would add
weight (the initial bundle is about 80 kB).

## Decision

Standalone Angular components, signals, design tokens in `frontend/src/styles.scss`,
light and dark themes, charts through the shared `baseOptions()`.

## Consequences

- Details: `docs/design/api-frontend.md`, section 13.
