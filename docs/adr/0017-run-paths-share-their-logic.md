# 17. Run paths share their logic

- **Status:** accepted, November 2026 (#66)

## Context

Ledger runs three ways: `./run.sh` (local or Docker), Docker Compose, and
`./kube.sh` with the Helm chart. `run.sh` and `kube.sh` each carried their own
copy of the same options (`--live`, `--port`, `--branch`, `--no-update`, ...),
defaults, port check, waiting loop and mode text. Compose and the chart both
define a few defaults (demo mode, the database file, ports, host names, image
names). The full stack stays on purpose: it is the learning goal.

## Decision

`run.sh` and `kube.sh` remain the only entry points. What they share lives once
in `scripts/lib/common.sh`: the defaults (`MODE`, `UPDATE`, `BRANCH`,
`SYSTEM_PACKAGES`, `OPEN_BROWSER`), `parse_common_option`, `validate_port`,
`common_options_help`, `wait_for_url` and `describe_mode`. The scripts keep
only what differs (their own options, their default port).

The chart cannot read files outside its own folder, so Compose and the chart
cannot share one defaults file. Each such setting is listed once in a table in
`docs/GUIDE.md` ("Settings the run paths define twice"), and
`tests/test_run_paths.py` fails when the copies that must match disagree.
Settings that differ on purpose (the browser port, the log format) are in the
same table with the reason.

The Helm value `dailyPrediction` is renamed `dailyAnalysis` and
`./kube.sh predict-now` is renamed `analyse-now`, to follow the glossary. The old
names keep working for one release and warn (see the CHANGELOG, "Deprecated").
Stored names (the `predictions` volume and PVC) are not renamed.

## Consequences

- Adding a shared option or default is one edit in `common.sh`.
- A new setting that two run paths must agree on needs a row in the table and a
  check in `tests/test_run_paths.py`.
- After one release the deprecated names and `apply_deprecated_names` in
  `kube.sh` are removed.
