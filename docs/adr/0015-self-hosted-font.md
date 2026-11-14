# 15. Self-host the font

- **Status:** accepted, November 2026

## Context

Google Fonts would add third-party requests and fail offline or in locked-down
deployments.

## Decision

The font is served with the app.

## Consequences

- The app works offline and sends no requests to third parties.
