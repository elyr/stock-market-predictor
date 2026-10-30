# Contributing

Thanks for helping improve Ledger. This page explains how to set up, how
changes are made, and what a pull request needs.

## Setup

```bash
git clone https://github.com/elyr/stock-market-predictor.git
cd stock-market-predictor
./run.sh --setup-only        # Python environment and web app build
./run.sh --test              # both test suites
scripts/check.sh --quick     # fast checks while you work; without --quick, what CI runs locally
```

Using an AI coding agent? Point it at [AGENTS.md](AGENTS.md): the project map,
commands, rules and pitfalls in one place (`CLAUDE.md` and
`.github/copilot-instructions.md` defer to it).

Without `run.sh`: see "Without Docker" in the [README](README.md#without-docker).
To work on the web app with live reload, see
[Developing the frontend](README.md#developing-the-frontend).

## How changes are made

1. **Start from an issue.** Every change links to one, so the reason is
   recorded. Use the issue templates.
2. **Branch from `main`**, named after the kind of change:
   `feature/…`, `fix/…`, `docs/…`, `chore/…`.
3. **Commit messages** start with a verb in the imperative and say what
   changes and why: `Add readiness endpoint for Kubernetes probes`.
4. **Open a pull request** with the template filled in and `Closes #N`.
   `main` is protected: changes arrive through pull requests with passing
   checks, and history stays linear (squash or rebase merges).
5. Add a line to `CHANGELOG.md` under **Unreleased**.

## Rules the code relies on

These are what make the results trustworthy. Reviews check them first.

- **No future information.** Features at date *t* use data up to *t*;
  training rows only use labels known at decision time. Two tests in the suite
  check this; keep them passing.
- **Stocks and crypto stay separate**: separate pipelines, models, settings and
  stored runs.
- **Evaluate honestly**: chronological, purged splits; report rank IC with
  t-statistics rather than raw accuracy.
- **Tests stay offline**: use `SyntheticDataCollector`; mark anything that needs
  the network with `@pytest.mark.network`.

## Style

- Python: type hints and docstrings, PEP 8.
- Frontend: standalone Angular components, signals for state, design tokens in
  `frontend/src/styles.scss`, no UI kit.
- Shell scripts: `shellcheck` clean (CI checks it).
- `.editorconfig` sets indentation and line endings for every editor.

## Checks that run on every pull request

| Workflow | What it checks |
|---|---|
| Tests | Python suite on 3.10, 3.12 and 3.13; Angular tests and build |
| Kubernetes | Helm lint and manifest validation; a full deploy with `kube.sh` on a k3d cluster |
| Daily prediction | Runs when the script changes: the day's prediction end to end |
| Release | Builds and scans the image; on `main` and tags publishes it (see [docs/RELEASING.md](docs/RELEASING.md)) |

## Releases

Versions follow [Semantic Versioning](https://semver.org/). A release moves the
"Unreleased" notes in `CHANGELOG.md` under a new version and tags it `vX.Y.Z`;
CI then publishes the image, the chart and the GitHub release. Step by step:
[docs/RELEASING.md](docs/RELEASING.md).
