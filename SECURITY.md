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
  `run.sh`) or a local cluster, and do not expose it to the internet. To share
  it, put an authenticating proxy in front (for example Cloudflare Access or
  oauth2-proxy).
- API keys (for example `ALPHA_VANTAGE_API_KEY`) belong in `.env` or a
  Kubernetes Secret, never in the repository. `.env` is ignored by git.

## What protects the project

| Area | Protection |
|---|---|
| Secrets | GitHub secret scanning with push protection, and gitleaks over the whole history on every pull request (`Security` workflow) |
| Dependencies | `pip-audit` and `npm audit` on every pull request and weekly; Dependabot update pull requests for Python, npm, GitHub Actions and Docker |
| Code | CodeQL code scanning (Python, TypeScript, Actions) |
| CI | Every workflow starts from read-only permissions and jobs ask for more only when they need it; third-party actions are pinned to commit SHAs; checkouts do not keep credentials; workflow inputs reach scripts through environment variables; `zizmor` audits the workflows on every pull request |
| Supply chain | Images are built once in CI, scanned with Grype, and published with build provenance and an SBOM; OpenSSF Scorecard rates the repository weekly |
| Runtime | The container runs as a non-root user; Kubernetes pods run as non-root with all capabilities dropped and no privilege escalation; the API sends a Content Security Policy (scripts only from the app itself), `X-Frame-Options: DENY`, `nosniff` and a strict referrer policy |
| Changes | `main` is protected: changes arrive through pull requests with passing checks |

## For maintainers

Two settings need the repository owner (Settings → Code security):
- turn on **Dependabot security updates**;
- turn on **private vulnerability reporting**, so the link above works.
