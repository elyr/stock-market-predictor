# Security policy

## Supported versions

Only the latest release and `main` receive fixes.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub security advisories](https://github.com/elyr/stock-market-predictor/security/advisories/new),
with the steps to reproduce and the version (`git log -1 --format=%h`).
You can expect a first answer within a week.

## Running Ledger safely

- **There is no login yet** (tracked in #4). Anyone who can reach the app can
  start training runs and backtests. Keep it on `127.0.0.1` (the default for
  `run.sh`) or a local cluster, and do not expose it to the internet.
- API keys (for example `ALPHA_VANTAGE_API_KEY`) belong in `.env` or a
  Kubernetes Secret, never in the repository. `.env` is ignored by git.
- The container runs as a non-root user with all Linux capabilities dropped.
- Dependabot opens weekly update pull requests for Python, npm, GitHub Actions
  and the Docker base images.
