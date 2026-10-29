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

# ------------------------------------------------------------------ output

if [ -t 1 ]; then
    BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
ok()   { printf '    %s%s%s\n' "$GREEN" "$*" "$RESET"; }
warn() { printf '%sWarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%sError:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

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
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "Invalid port: $PORT"

# ---------------------------------------------------------------- helpers

have() { command -v "$1" >/dev/null 2>&1; }

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif have sudo; then sudo "$@"
    else die "Need administrator rights to run: $*"
    fi
}

# Install system packages with pacman (Arch, CachyOS, Manjaro, EndeavourOS).
# pacman asks before changing anything, e.g. replacing an incompatible Node.js.
install_packages() {
    if [ "$SYSTEM_PACKAGES" -eq 0 ]; then
        die "Missing: $*. Install it, or run without --no-system-packages."
    fi
    if have pacman; then
        step "Installing system packages: $* (you may be asked for your password)"
        as_root pacman -S --needed "$@"
    else
        die "Missing: $*. This script installs packages automatically on Arch-based systems only; please install it with your package manager and run ./run.sh again."
    fi
}

hash_of() { sha256sum "$@" | sha256sum | cut -c1-16; }

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

# True when nothing is listening on the port (uses bash's /dev/tcp, no extra tools)
port_free() {
    ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

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

open_browser() {
    [ "$OPEN_BROWSER" -eq 1 ] || return 0
    local url="http://127.0.0.1:$PORT"
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && have xdg-open; then
        xdg-open "$url" >/dev/null 2>&1 &
    fi
}

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

# ------------------------------------------------------------------ update

# Bring the clone up to date with GitHub. Only fast-forwards: local edits and
# local commits are never overwritten (the update is skipped with a message).
update_code() {
    [ "$UPDATE" -eq 1 ] || return 0
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        warn "This folder is not a git clone, so it cannot update itself. Starting the version you have."
        return 0
    fi

    step "Checking GitHub for updates to $BRANCH"
    if ! git fetch --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null; then
        warn "Could not fetch '$BRANCH' from GitHub (offline, or no such branch). Starting the version you have."
        return 0
    fi
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        warn "You have uncommitted changes, so the update was skipped. Starting your version."
        warn "To update anyway: git stash, then ./run.sh (git stash pop brings your changes back)."
        return 0
    fi

    local before after current
    before="$(git rev-parse HEAD)"
    current="$(git symbolic-ref --quiet --short HEAD || true)"
    if ! git cat-file -e "origin/$BRANCH:run.sh" 2>/dev/null; then
        warn "'$BRANCH' on GitHub does not contain run.sh yet (merge the branch that adds it first)."
        warn "Staying on ${current:-the current commit}. To follow another branch: ./run.sh --branch NAME"
        return 0
    fi
    if [ "$current" != "$BRANCH" ]; then
        if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
            git checkout --quiet "$BRANCH" || { warn "Could not switch to $BRANCH. Starting the current version."; return 0; }
        else
            git checkout --quiet -b "$BRANCH" --track "origin/$BRANCH" \
                || { warn "Could not switch to $BRANCH. Starting the current version."; return 0; }
        fi
        ok "Switched from ${current:-a detached commit} to $BRANCH"
    fi
    if ! git merge --ff-only --quiet "origin/$BRANCH" 2>/dev/null; then
        warn "Your local $BRANCH has commits that are not on GitHub, so it was not updated. Starting your version."
        return 0
    fi

    after="$(git rev-parse HEAD)"
    if [ "$before" = "$after" ]; then
        ok "Already up to date ($(git log -1 --format='%h, %s' | cut -c1-70))"
        return 0
    fi
    local count
    count="$(git rev-list --count "$before..$after" 2>/dev/null || echo "?")"
    ok "Updated to the latest $BRANCH: $count new commit(s)"
    git log --format='      %h %s' --no-merges -n 10 "$before..$after" 2>/dev/null | cut -c1-100 || true

    # If this script itself changed, continue with the new version of it
    if ! git diff --quiet "$before" "$after" -- run.sh 2>/dev/null; then
        step "run.sh was updated too; continuing with the new version"
        exec "$ROOT/run.sh" --no-update "${ORIGINAL_ARGS[@]}"
    fi
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
    if ! have docker; then
        install_packages docker docker-compose docker-buildx
    fi
    docker compose version >/dev/null 2>&1 || install_packages docker-compose
    if ! systemctl is-active --quiet docker 2>/dev/null; then
        step "Starting the Docker service"
        as_root systemctl enable --now docker
    fi

    local use_sudo=0
    if ! docker info >/dev/null 2>&1; then
        use_sudo=1
        warn "Using sudo for Docker. To avoid that: sudo usermod -aG docker ${USER:-$(id -un)}, then log out and back in."
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
