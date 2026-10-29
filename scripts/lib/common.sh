# Shared helpers for run.sh and kube.sh. Sourced, not run.
#
# The sourcing script sets, before calling these functions:
#   ROOT             repository root
#   SELF             the script's file name (run.sh or kube.sh)
#   ORIGINAL_ARGS    the script's original arguments (array)
#   UPDATE, BRANCH   update settings (update_code)
#   SYSTEM_PACKAGES  1 to allow installing packages (install_packages)
#   OPEN_BROWSER     1 to open the browser (open_url)
# shellcheck shell=bash disable=SC2034  # variables here are read by the sourcing script

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

# ---------------------------------------------------------------- system

have() { command -v "$1" >/dev/null 2>&1; }

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif have sudo; then sudo "$@"
    else die "Need administrator rights to run: $*"
    fi
}

# Install system packages with pacman (Arch, CachyOS, Manjaro, EndeavourOS).
# pacman asks before changing anything, e.g. replacing an incompatible package.
install_packages() {
    if [ "${SYSTEM_PACKAGES:-1}" -eq 0 ]; then
        die "Missing: $*. Install it, or run without --no-system-packages."
    fi
    if have pacman; then
        step "Installing system packages: $* (you may be asked for your password)"
        as_root pacman -S --needed "$@"
    else
        die "Missing: $*. Packages are installed automatically on Arch-based systems only; please install it with your package manager and run ./${SELF:-run.sh} again."
    fi
}

hash_of() { sha256sum "$@" | sha256sum | cut -c1-16; }

# True when nothing is listening on the port (uses bash's /dev/tcp, no extra tools)
port_free() {
    ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

open_url() {
    [ "${OPEN_BROWSER:-1}" -eq 1 ] || return 0
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && have xdg-open; then
        xdg-open "$1" >/dev/null 2>&1 &
    fi
    return 0
}

# Make sure Docker is installed and its service is running. Sets DOCKER_NEEDS_SUDO
# to 1 when the current user cannot use Docker without sudo yet.
ensure_docker() {
    if ! have docker; then
        install_packages docker docker-compose docker-buildx
    fi
    if ! systemctl is-active --quiet docker 2>/dev/null; then
        step "Starting the Docker service"
        as_root systemctl enable --now docker
    fi
    declare -g DOCKER_NEEDS_SUDO=0   # read by the scripts that source this file
    if ! docker info >/dev/null 2>&1; then
        declare -g DOCKER_NEEDS_SUDO=1
    fi
}

docker_group_hint() {
    echo "sudo usermod -aG docker ${USER:-$(id -un)}, then log out and back in (or run: newgrp docker)"
}

# ------------------------------------------------------------------ update

# Bring the clone up to date with GitHub. Only fast-forwards: local edits and
# local commits are never overwritten (the update is skipped with a message).
# When the script or this library changed, the new version is started instead.
update_code() {
    [ "${UPDATE:-1}" -eq 1 ] || return 0
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        warn "This folder is not a git clone, so it cannot update itself. Using the version you have."
        return 0
    fi

    step "Checking GitHub for updates to $BRANCH"
    if ! git fetch --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null; then
        warn "Could not fetch '$BRANCH' from GitHub (offline, or no such branch). Using the version you have."
        return 0
    fi
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        warn "You have uncommitted changes, so the update was skipped. Using your version."
        warn "To update anyway: git stash, then ./$SELF (git stash pop brings your changes back)."
        return 0
    fi

    local before after current
    before="$(git rev-parse HEAD)"
    current="$(git symbolic-ref --quiet --short HEAD || true)"
    if ! git cat-file -e "origin/$BRANCH:$SELF" 2>/dev/null; then
        warn "'$BRANCH' on GitHub does not contain $SELF yet (merge the branch that adds it first)."
        warn "Staying on ${current:-the current commit}. To follow another branch: ./$SELF --branch NAME"
        return 0
    fi
    if [ "$current" != "$BRANCH" ]; then
        if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
            git checkout --quiet "$BRANCH" || { warn "Could not switch to $BRANCH. Using the current version."; return 0; }
        else
            git checkout --quiet -b "$BRANCH" --track "origin/$BRANCH" \
                || { warn "Could not switch to $BRANCH. Using the current version."; return 0; }
        fi
        ok "Switched from ${current:-a detached commit} to $BRANCH"
    fi
    if ! git merge --ff-only --quiet "origin/$BRANCH" 2>/dev/null; then
        warn "Your local $BRANCH has commits that are not on GitHub, so it was not updated. Using your version."
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

    # If this script or its library changed, continue with the new version
    if ! git diff --quiet "$before" "$after" -- "$SELF" scripts/lib/ 2>/dev/null; then
        step "$SELF was updated too; continuing with the new version"
        exec "$ROOT/$SELF" --no-update "${ORIGINAL_ARGS[@]}"
    fi
}
