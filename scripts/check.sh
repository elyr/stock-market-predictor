#!/usr/bin/env bash
# Run the checks CI runs that do not need a Kubernetes cluster.
#
#   scripts/check.sh            full Python suite, frontend tests and build, shellcheck,
#                               and promtool / helm lint when they are installed
#   scripts/check.sh --quick    the fast Python tests only (models, forecast, API wiring)
#                               plus the frontend tests and build
#
# Exits non-zero on the first failure. Meant for people and coding agents alike.
set -euo pipefail

cd "$(dirname "$0")/.."
QUICK=0
for arg in "$@"; do
    case "$arg" in
        --quick) QUICK=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

PYTHON="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PYTHON=.venv/bin/python

step() { printf '\n==> %s\n' "$*"; }

if [ "$QUICK" -eq 1 ]; then
    step "Python: targeted tests"
    "$PYTHON" -m pytest -q tests/test_cross_section.py tests/test_forecast.py tests/test_ranker.py
else
    step "Python: full test suite (several minutes)"
    "$PYTHON" -m pytest -q
fi

step "Frontend: tests and build"
(
    cd frontend
    [ -d node_modules ] || npm ci
    npx ng test --watch=false
    npx ng build
)

if [ "$QUICK" -eq 0 ]; then
    if command -v shellcheck >/dev/null; then
        step "shellcheck"
        shellcheck -x run.sh kube.sh scripts/lib/common.sh scripts/check.sh
    else
        echo "shellcheck not installed: skipped"
    fi
    if command -v promtool >/dev/null; then
        step "Alert rules (promtool)"
        promtool check rules deploy/helm/ledger/files/alert-rules.yaml
        promtool test rules tests/prometheus/alert-rules.test.yaml
    else
        echo "promtool not installed: skipped"
    fi
    if command -v helm >/dev/null; then
        step "Helm chart"
        helm lint --strict deploy/helm/ledger
    else
        echo "helm not installed: skipped"
    fi
fi

step "All checks passed"
