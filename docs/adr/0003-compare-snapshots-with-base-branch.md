# 3. Compare analysis snapshots with the base branch

- **Status:** accepted, November 2026

## Context

Refactors must not change any number the app shows. Library versions (pandas,
numpy) move the numbers, so snapshots recorded once and committed would fail
for reasons unrelated to a change, and would hide real changes behind updates.

## Decision

`tests/test_snapshots.py` runs fixed-seed analyses end to end on the synthetic
market and compares them with snapshots that are **not committed**. Snapshots
are recorded from the code before the change, in the same environment:
`UPDATE_SNAPSHOTS=1 python3 -m pytest -q tests/test_snapshots.py` on `main`,
then the same test without the variable on the change. In CI, the Snapshots job
of the Tests workflow checks out the pull request's base commit, records the
snapshots there and compares the pull request against them. A pull request that
changes the numbers on purpose gets the `changes-output` label, which skips the job.

## Consequences

- Without recorded snapshots the tests are skipped, so a local run proves
  nothing until a baseline exists.
- A change to the output is always a visible, labelled decision.
- A dependency bump that changes output shows up as a failure of the same job.
