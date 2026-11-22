# 18. One component layout

- **Status:** accepted, November 2026 (#70)

## Context

Angular components were written two ways. Five pages kept their template and
styles in `.html` and `.scss` files, eleven kept templates of 50 to 250 lines
inside the `.ts` file as a template string. A page template and the component
class mixed in one long file are hard to read, edit and diff, while splitting a
15-line component into three files costs more than it gives.

## Decision

One rule for every component under `frontend/src/app`: a template of 40 lines
or fewer is inline, with inline `styles`; a longer template is in
`<component>.html` and its styles in `<component>.scss`, next to the component
and named after it. The two layouts are never mixed. The rule is in `AGENTS.md`
and enforced by `scripts/check_code.py` (CI's Code job), which also rejects a
`.html` or `.scss` file that no component uses.

## Consequences

- The 11 pages with long inline templates were split; no template or style
  changed (checked with screenshots of every page).
- A component that grows past 40 lines of template has to be split, and one that
  shrinks below 40 has to move back inline, so the choice never needs a debate.
- Pages, routes, menu entries and file names are unchanged.
