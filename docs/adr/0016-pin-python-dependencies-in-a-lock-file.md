# 16. Pin the Python dependencies in a lock file

- **Status:** accepted, November 2026 (#118)

## Context

`requirements.txt` lists minimum versions, so every install took the newest
releases. A pandas minor release changed some results (see
`docs/research/2026-11-predictor-review.md` and the docstring of
`tests/test_snapshots.py`), and CI, the Docker image and `./run.sh` could each
run different versions on the same day.

## Decision

`requirements.txt` stays the list of direct dependencies. `requirements.lock`
pins every package with its hash, made with `uv pip compile --universal
--python-version 3.10 --generate-hashes`, so one file holds the right versions
for Python 3.10 to 3.13 (as markers). CI, the Dockerfile and `./run.sh` install
from it. Dependabot cannot update this format, so the lock is refreshed by hand
with the command at the top of `requirements.txt`, and a CI job fails when the
two files disagree.

## Consequences

- Rebuilding gives the same versions. Taking newer releases is a visible change
  that has to pass the snapshot comparison first.
- The lock holds the newest versions that still support Python 3.10, which can
  carry advisories whose fixes need 3.11 or later. The Security job audits what
  the lock installs on Python 3.12.
- Nobody gets newer releases until someone refreshes the lock.
