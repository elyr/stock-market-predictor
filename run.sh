#!/usr/bin/env bash
# Ledger: update, set up and start the whole app with one command.
#
#   git clone https://github.com/elyr/stock-market-predictor.git
#   cd stock-market-predictor
#   ./run.sh                 # simulated prices, works offline, dashboards fill themselves
#   ./run.sh --live          # real Yahoo Finance prices
#
# Every run:
#   1. fetches the latest main from GitHub and fast-forwards to it (local
#      changes are never overwritten; if there are any, it says so and skips),
#   2. installs what is missing (asking for your password on Arch-based
#      systems such as CachyOS) and rebuilds only what changed,
#   3. stops the copy it started last time, if still running, then starts the
#      new version and opens your browser.
#
# So after merging a pull request on GitHub, running ./run.sh again is all it
# takes to use the new version. Press Ctrl+C to stop the app.
#
# Run ./run.sh --help for all options.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
ORIGINAL_ARGS=("$@")

PYTHON_VERSION="3.12"
VENV="$ROOT/.venv"
FRONTEND="$ROOT/frontend"
DIST_INDEX="$FRONTEND/dist/frontend/browser/index.html"
PID_FILE="$ROOT/.run/ledger.pid"

MODE="demo"
USE_DOCKER=0
PORT=8000
OPEN_BROWSER=1
RUN_TESTS=0
SETUP_ONLY=0
SYSTEM_PACKAGES=1
UPDATE=1
BRANCH="main"

# Shared helpers: output, package installs, the GitHub update (scripts/lib/common.sh)
SELF="run.sh"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

usage() {
    cat <<EOF
Usage: ./run.sh [options]

Updates Ledger from GitHub, installs and builds whatever is missing or changed,
and starts it at http://127.0.0.1:$PORT.

Options:
  --live            Use real Yahoo Finance prices (default: simulated demo prices)
  --demo            Use simulated prices (the default)
  --docker          Run in Docker instead of a local Python environment
  --port N          Port to serve on (default: 8000)
  --test            Run the Python and frontend test suites, then exit
  --setup-only      Install and build, but do not start the app
  --no-browser      Do not open the browser
  --branch NAME     Follow another branch instead of main (e.g. to try a pull
                    request before merging it)
  --no-update       Start the version you already have, without checking GitHub
  --no-system-packages
                    Never install system packages; only report what is missing
  -h, --help        Show this help

Demo and live data are kept in separate databases (data/demo.db and
data/predictions.db), so switching between them never mixes results.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --live) MODE="live" ;;
        --demo) MODE="demo" ;;
        --docker) USE_DOCKER=1 ;;
        --port) shift; [ $# -gt 0 ] || die "--port needs a number"; PORT="$1" ;;
        --port=*) PORT="${1#*=}" ;;
        --test) RUN_TESTS=1 ;;
        --setup-only) SETUP_ONLY=1 ;;
        --no-browser) OPEN_BROWSER=0 ;;
        --no-system-packages) SYSTEM_PACKAGES=0 ;;
        --no-update) UPDATE=0 ;;
        --branch) shift; [ $# -gt 0 ] || die "--branch needs a name"; BRANCH="$1" ;;
        --branch=*) BRANCH="${1#*=}" ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "Unknown option: $1" ;;
    esac
    shift
done
{ [[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ]; } || die "Invalid port: $PORT"

# ---------------------------------------------------------------- helpers

# Node.js versions supported by the frontend toolchain (Angular 22)
node_supported() {
    local version major minor patch
    version="$(node --version 2>/dev/null)" || return 1
    version="${version#v}"
    IFS=. read -r major minor patch <<<"$version"
    patch="${patch%%[!0-9]*}"
    [ -n "$major" ] && [ -n "$minor" ] && [ -n "$patch" ] || return 1
    if [ "$major" -ge 26 ]; then return 0; fi
    if [ "$major" -eq 24 ]; then [ "$minor" -ge 15 ]; return; fi
    if [ "$major" -eq 22 ]; then [ "$minor" -gt 22 ] || { [ "$minor" -eq 22 ] && [ "$patch" -ge 3 ]; }; return; fi
    return 1
}

python_in_venv() { "$VENV/bin/python" "$@"; }

wait_for_app() {
    local url="http://127.0.0.1:$PORT/api/health" tries="${1:-120}"
    for _ in $(seq 1 "$tries"); do
        if have curl; then
            curl -fsS --max-time 2 "$url" >/dev/null 2>&1 && return 0
        else
            python3 -c "import urllib.request; urllib.request.urlopen('$url', timeout=2)" >/dev/null 2>&1 && return 0
        fi
        sleep 1
    done
    return 1
}

open_browser() { open_url "http://127.0.0.1:$PORT"; }

describe_mode() {
    if [ "$MODE" = "demo" ]; then
        echo "Demo mode: simulated prices. Both dashboards fill themselves within a few minutes."
        echo "For real prices, stop with Ctrl+C and run: ./run.sh --live"
    else
        echo "Live mode: real Yahoo Finance prices. Click \"Run analysis\" on each dashboard to start."
    fi
}

gpu_note() {
    if have nvidia-smi; then
        local gpu
        gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
        [ -n "$gpu" ] && ok "GPU found ($gpu). The current app runs on the CPU; the GPU is not needed."
    fi
    return 0
}

# Ask the server to stop; if it is busy with a long job (training, a backtest)
# it may not exit by itself, so stop it outright after 10 seconds.
stop_server() {
    local pid="$1"
    kill "$pid" 2>/dev/null || return 0
    for _ in $(seq 1 40); do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
}

# Stop the Ledger this script started last time, if it is still running
stop_previous() {
    [ -f "$PID_FILE" ] || return 0
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && grep -qa "api.main:app" "/proc/$pid/cmdline" 2>/dev/null; then
        step "Stopping the copy of Ledger that is already running"
        stop_server "$pid"
    fi
    rm -f "$PID_FILE"
}

# ------------------------------------------------------------- local setup

setup_python() {
    step "Python environment"
    if ! have uv; then
        if have pacman; then
            install_packages uv
        elif [ "$SYSTEM_PACKAGES" -eq 1 ] && have curl; then
            step "Installing uv (Python package manager) into ~/.local/bin"
            curl -LsSf https://astral.sh/uv/install.sh | sh
            export PATH="$HOME/.local/bin:$PATH"
        else
            die "Missing: uv. Install it from https://docs.astral.sh/uv/ and run ./run.sh again."
        fi
    fi
    if [ ! -x "$VENV/bin/python" ] || ! python_in_venv -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))"; then
        step "Creating a Python $PYTHON_VERSION environment in .venv (uv downloads Python if needed)"
        rm -rf "$VENV"
        uv venv --quiet --python "$PYTHON_VERSION" "$VENV"
    fi
    local want have_hash
    want="$(hash_of requirements.txt)"
    have_hash="$(cat "$VENV/.requirements-hash" 2>/dev/null || true)"
    if [ "$want" != "$have_hash" ]; then
        step "Installing Python packages (first time takes a few minutes)"
        uv pip install --quiet --python "$VENV/bin/python" -r requirements.txt
        echo "$want" > "$VENV/.requirements-hash"
    fi
    ok "Python $(python_in_venv -c 'import platform; print(platform.python_version())') ready"
}

setup_frontend() {
    step "Web app"
    if ! node_supported; then
        if have node; then
            warn "Node.js $(node --version) is not supported by the web app (needs 22.22.3+, 24.15+ or 26+)."
        fi
        if have pacman; then
            # nodejs-lts-jod is Node 22 LTS; pacman asks before replacing another Node.js package
            install_packages nodejs-lts-jod npm
        else
            install_packages nodejs npm
        fi
        node_supported || die "Node.js $(node --version 2>/dev/null || echo 'is missing') is not supported. Install Node 22 LTS or 24 LTS and run ./run.sh again."
    fi
    have npm || install_packages npm

    local want have_hash
    want="$(hash_of "$FRONTEND/package-lock.json")"
    have_hash="$(cat "$FRONTEND/node_modules/.lock-hash" 2>/dev/null || true)"
    if [ ! -d "$FRONTEND/node_modules" ] || [ "$want" != "$have_hash" ]; then
        step "Installing web app packages"
        (cd "$FRONTEND" && npm ci --no-audit --no-fund --loglevel=error)
        echo "$want" > "$FRONTEND/node_modules/.lock-hash"
    fi

    local stale=""
    if [ -f "$DIST_INDEX" ]; then
        stale="$(find "$FRONTEND/src" "$FRONTEND/public" "$FRONTEND/angular.json" "$FRONTEND/package-lock.json" \
                   "$FRONTEND/tsconfig.json" "$FRONTEND/tsconfig.app.json" -newer "$DIST_INDEX" -print -quit 2>/dev/null || true)"
    fi
    if [ ! -f "$DIST_INDEX" ] || [ -n "$stale" ]; then
        step "Building the web app"
        (cd "$FRONTEND" && npx ng build --progress=false >/dev/null) || die "The web app build failed. Run 'cd frontend && npx ng build' to see why."
    fi
    ok "Node.js $(node --version) ready, web app built"
}

run_tests() {
    step "Running the Python tests (about 3 minutes)"
    python_in_venv -m pytest -q
    step "Running the web app tests"
    (cd "$FRONTEND" && npx ng test --watch=false)
    ok "All tests passed"
}

start_local() {
    stop_previous
    if ! port_free "$PORT"; then
        if wait_for_app 1; then
            die "A copy of Ledger that run.sh did not start is using port $PORT. Stop it first, or use: ./run.sh --port 8080"
        fi
        die "Port $PORT is already in use by another program. Try: ./run.sh --port 8080"
    fi
    mkdir -p "$ROOT/data" "$ROOT/logs"
    if [ "$MODE" = "demo" ]; then
        export DEMO_MODE=true DATABASE_PATH="$ROOT/data/demo.db"
    else
        export DEMO_MODE=false DATABASE_PATH="$ROOT/data/predictions.db"
    fi
    export FRONTEND_DIST="$FRONTEND/dist/frontend/browser"

    step "Starting Ledger"
    # Start the server binary itself (not via a shell function) so $! is its process ID
    "$VENV/bin/python" -m uvicorn api.main:app --host 127.0.0.1 --port "$PORT" --log-level warning &
    local pid=$!
    mkdir -p "$(dirname "$PID_FILE")"
    echo "$pid" > "$PID_FILE"
    trap 'echo; echo "Stopping Ledger..."; stop_server "$pid"; rm -f "$PID_FILE"; echo "Ledger stopped."; exit 0' INT TERM
    if ! wait_for_app 90; then
        kill "$pid" 2>/dev/null || true
        die "Ledger did not start. See the messages above."
    fi
    echo
    printf '%sLedger is running at http://127.0.0.1:%s%s\n' "$BOLD" "$PORT" "$RESET"
    describe_mode
    echo "Press Ctrl+C to stop."
    echo
    open_browser
    wait "$pid" || true
    rm -f "$PID_FILE"
}

# ------------------------------------------------------------------ docker

run_docker() {
    ensure_docker
    docker compose version >/dev/null 2>&1 || install_packages docker-compose

    local use_sudo="$DOCKER_NEEDS_SUDO"
    if [ "$use_sudo" -eq 1 ]; then
        warn "Using sudo for Docker. To avoid that: $(docker_group_hint)."
    fi

    local demo="true" database="/app/data/demo.db"
    if [ "$MODE" = "live" ]; then demo="false"; database="/app/data/predictions.db"; fi
    port_free "$PORT" || die "Port $PORT is already in use. Try: ./run.sh --docker --port 8080"

    step "Building and starting the containers (the first build takes 5 to 10 minutes)"
    describe_mode
    (wait_for_app 1800 && printf '\n%sLedger is running at http://127.0.0.1:%s%s (Ctrl+C to stop)\n\n' \
        "$BOLD" "$PORT" "$RESET" && open_browser) &
    DOCKER_WAITER=$!
    trap 'kill "${DOCKER_WAITER:-}" 2>/dev/null || true' EXIT
    local -a compose=(env DEMO_MODE="$demo" DATABASE_PATH="$database" PORT="$PORT" docker compose up --build)
    if [ "$use_sudo" -eq 1 ]; then
        as_root "${compose[@]}"
    else
        "${compose[@]}"
    fi
}

# -------------------------------------------------------------------- main

main() {
    printf '%sLedger%s, %s mode\n' "$BOLD" "$RESET" "$MODE"
    have git || install_packages git
    update_code
    gpu_note

    if [ "$USE_DOCKER" -eq 1 ]; then
        [ "$RUN_TESTS" -eq 0 ] || die "--test runs locally; drop --docker"
        run_docker
        return 0
    fi

    setup_python
    setup_frontend

    if [ "$RUN_TESTS" -eq 1 ]; then
        run_tests
        return 0
    fi
    if [ "$SETUP_ONLY" -eq 1 ]; then
        ok "Setup complete. Start the app with: ./run.sh"
        return 0
    fi
    start_local
}

# Run only when executed, not when sourced (the tests source this file to check its functions)
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main
fi
