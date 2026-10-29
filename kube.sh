#!/usr/bin/env bash
# Ledger on a local Kubernetes cluster (k3d), deployed with its Helm chart.
#
#   ./kube.sh up             # update from GitHub, create the cluster, build, deploy, open the browser
#   ./kube.sh status         # what is running
#   ./kube.sh predict-now    # run the daily prediction job now
#   ./kube.sh results        # copy the latest prediction results to ./results/
#   ./kube.sh down           # remove the app (the data is kept)
#   ./kube.sh destroy        # delete the whole local cluster
#
# The cluster is a k3s cluster running inside Docker (k3d), so nothing is
# installed on your machine besides the command-line tools. This script only
# ever talks to that cluster (context k3d-ledger), never to any other.
#
# Run ./kube.sh help for all commands and options. Guide: docs/KUBERNETES.md

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
ORIGINAL_ARGS=("$@")

CLUSTER="ledger"
CONTEXT="k3d-$CLUSTER"
NAMESPACE="ledger"
RELEASE="ledger"
CHART="$ROOT/deploy/helm/ledger"
HOST="ledger.localhost"
MLFLOW_HOST="mlflow.localhost"
GRAFANA_HOST="grafana.localhost"
PROMETHEUS_HOST="prometheus.localhost"
IMAGE_REPO="ledger"
GHCR_IMAGE="ghcr.io/elyr/stock-market-predictor"
FLUX_VERSION="2.7.5"
GITOPS_FILES="$ROOT/deploy/gitops"

COMMAND="up"
MODE="demo"
PROFILE="laptop"
PORT=8080
OPEN_BROWSER=1
SYSTEM_PACKAGES=1
UPDATE=1
BRANCH="main"
ASSUME_YES=0
MONITORING=""   # empty: keep what is deployed (off for a new install)
GITOPS=""       # empty: keep the current way of deploying (Helm from here for a new install)
BUILD=0
CMD_ARG=""
WAIT_TIMEOUT="15m"

SELF="kube.sh"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

usage() {
    cat <<EOF
Usage: ./kube.sh [command] [options]

Runs Ledger on a local Kubernetes cluster (k3d) with its Helm chart, at
http://$HOST:$PORT

Commands:
  up                Update from GitHub, install missing tools, create the
                    cluster if needed, build the image, deploy and open the
                    browser (the default)
  status            Show the release, pods, scheduled jobs and volumes
  logs [what]       Follow logs: server (default), mlflow, prometheus, grafana,
                    scans or prediction
  predict-now       Run the daily prediction job now and follow its output
  results [DIR]     Copy the latest prediction results to DIR (default: ./results)
  test              Run the chart's tests against the running app (helm test)
  down              Uninstall the app; the data volumes are kept
  destroy           Delete the local cluster and everything in it
  help              Show this help

Options for up:
  --live            Use real Yahoo Finance prices (default: simulated demo prices)
  --demo            Use simulated prices (the default)
  --profile NAME    Resource sizes: laptop (default) or desktop
  --monitoring      Also deploy Prometheus and Grafana (kept on for later runs)
  --no-monitoring   Remove Prometheus and Grafana
  --gitops          Let Flux deploy from GitHub: the image CI published for the
                    latest commit (kept on for later runs; see docs/RELEASING.md)
  --build           With --gitops: run an image built here instead (to try changes)
  --no-gitops       Back to deploying with Helm from this folder
  --port N          Port for the browser (default: 8080; used when the cluster
                    is created, so changing it later needs: ./kube.sh destroy)
  --branch NAME     Follow another branch instead of main
  --no-update       Deploy the version you already have, without checking GitHub
  --no-browser      Do not open the browser
  --no-system-packages
                    Never install packages; only report what is missing
Other options:
  -y, --yes         Do not ask for confirmation (destroy)
  -h, --help        Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        up|status|logs|predict-now|results|test|down|destroy|help) COMMAND="$1"
            # logs and results take an optional argument
            if [[ "$1" =~ ^(logs|results)$ ]] && [ $# -gt 1 ] && [[ "$2" != -* ]]; then shift; CMD_ARG="$1"; fi
            ;;
        --live) MODE="live" ;;
        --demo) MODE="demo" ;;
        --gitops) GITOPS=true ;;
        --no-gitops) GITOPS=false ;;
        --build) BUILD=1 ;;
        --monitoring) MONITORING=true ;;
        --no-monitoring) MONITORING=false ;;
        --profile) shift; [ $# -gt 0 ] || die "--profile needs a name"; PROFILE="$1" ;;
        --profile=*) PROFILE="${1#*=}" ;;
        --port) shift; [ $# -gt 0 ] || die "--port needs a number"; PORT="$1" ;;
        --port=*) PORT="${1#*=}" ;;
        --branch) shift; [ $# -gt 0 ] || die "--branch needs a name"; BRANCH="$1" ;;
        --branch=*) BRANCH="${1#*=}" ;;
        --no-update) UPDATE=0 ;;
        --no-browser) OPEN_BROWSER=0 ;;
        --no-system-packages) SYSTEM_PACKAGES=0 ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) COMMAND="help" ;;
        *) usage >&2; die "Unknown command or option: $1" ;;
    esac
    shift
done
{ [[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ]; } || die "Invalid port: $PORT"
case "$PROFILE" in laptop|desktop) ;; *) die "Unknown profile: $PROFILE (use laptop or desktop)" ;; esac

# Every kubectl and helm call names the cluster explicitly, so other clusters
# in your kubeconfig are never touched
k() { kubectl --context "$CONTEXT" -n "$NAMESPACE" "$@"; }
h() { helm --kube-context "$CONTEXT" -n "$NAMESPACE" "$@"; }

# ------------------------------------------------------------------- tools

install_k3d() {
    if [ "$SYSTEM_PACKAGES" -eq 0 ]; then
        die "Missing: k3d. Install it (https://k3d.io), or run without --no-system-packages."
    fi
    have curl || install_packages curl
    step "Installing k3d into ~/.local/bin"
    mkdir -p "$HOME/.local/bin"
    curl -fsSL https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh \
        | K3D_INSTALL_DIR="$HOME/.local/bin" USE_SUDO=false bash
}

ensure_tools() {
    step "Tools"
    export PATH="$HOME/.local/bin:$PATH"
    have git || install_packages git
    ensure_docker
    if [ "$DOCKER_NEEDS_SUDO" -eq 1 ]; then
        # k3d must use Docker as you, not as root, so the cluster ends up in your kubeconfig
        if [ "$SYSTEM_PACKAGES" -eq 1 ] && ! id -nG | tr ' ' '\n' | grep -qx docker; then
            step "Adding you to the docker group so Docker works without sudo"
            as_root usermod -aG docker "${USER:-$(id -un)}"
        fi
        die "Docker needs sudo in this session. Log out and back in (or run: newgrp docker), then run ./kube.sh up again."
    fi
    local -a missing=()
    have kubectl || missing+=(kubectl)
    have helm || missing+=(helm)
    [ ${#missing[@]} -eq 0 ] || install_packages "${missing[@]}"
    have k3d || install_k3d
    have k3d || die "k3d was installed but is not on your PATH. Add ~/.local/bin to PATH and run again."
    ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), kubectl $(kubectl version --client -o json 2>/dev/null | sed -n 's/.*"gitVersion": *"\([^"]*\)".*/\1/p' | head -1), helm $(helm version --short 2>/dev/null), $(k3d version 2>/dev/null | head -1)"
}

need_cluster() {
    { have kubectl && have helm && have k3d; } || die "Tools are missing. Run ./kube.sh up first."
    k3d cluster get "$CLUSTER" >/dev/null 2>&1 || die "The local cluster does not exist. Run ./kube.sh up first."
    kubectl --context "$CONTEXT" get --raw /readyz >/dev/null 2>&1 \
        || die "The cluster is not running. Start it with: k3d cluster start $CLUSTER (or ./kube.sh up)"
}

# ----------------------------------------------------------------- cluster

cluster_port() {
    docker port "k3d-$CLUSTER-serverlb" 80/tcp 2>/dev/null | head -1 | sed 's/.*://'
}

ensure_cluster() {
    step "Cluster"
    if k3d cluster get "$CLUSTER" >/dev/null 2>&1; then
        if ! kubectl --context "$CONTEXT" get --raw /readyz >/dev/null 2>&1; then
            step "Starting the existing cluster '$CLUSTER'"
            k3d cluster start "$CLUSTER" --wait
        fi
        local existing
        existing="$(cluster_port)"
        if [ -n "$existing" ] && [ "$existing" != "$PORT" ]; then
            warn "The cluster was created with port $existing, so the app is at http://$HOST:$existing"
            warn "To use port $PORT instead: ./kube.sh destroy, then ./kube.sh up --port $PORT"
            PORT="$existing"
        fi
        ok "Cluster '$CLUSTER' is running"
    else
        port_free "$PORT" || die "Port $PORT is already in use. Try: ./kube.sh up --port 8081"
        step "Creating the local cluster '$CLUSTER' (one node, about a minute)"
        k3d cluster create "$CLUSTER" \
            --port "$PORT:80@loadbalancer" \
            --kubeconfig-update-default \
            --kubeconfig-switch-context=false \
            --wait
        ok "Cluster '$CLUSTER' created (kubectl context: $CONTEXT)"
    fi
    # Traefik (k3s's ingress controller) is installed in the background on a new cluster
    local _
    for _ in $(seq 1 60); do
        kubectl --context "$CONTEXT" get ingressclass traefik >/dev/null 2>&1 && return 0
        sleep 3
    done
    warn "The ingress controller (Traefik) is not ready yet; the app may take a moment to be reachable."
}

# ------------------------------------------------------------------- image

image_tag() {
    local tag
    tag="$(git rev-parse --short HEAD 2>/dev/null || echo local)"
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        # Uncommitted changes get their own tag, so each build is deployed
        tag="$tag-dirty-$( { git diff HEAD 2>/dev/null; git status --porcelain 2>/dev/null; } | sha256sum | cut -c1-8)"
    fi
    echo "$tag"
}

build_image() {
    IMAGE_TAG="$(image_tag)"
    local image="$IMAGE_REPO:$IMAGE_TAG"
    step "Building the image $image (the first build takes 5 to 10 minutes)"
    docker build --quiet --build-arg "GIT_COMMIT=$IMAGE_TAG" -t "$image" "$ROOT" >/dev/null
    step "Loading the image into the cluster"
    k3d image import "$image" -c "$CLUSTER" >/dev/null
    ok "Image $image ready in the cluster"
}

# ------------------------------------------------------------------ deploy

monitoring_deployed() {
    k get deployment "$RELEASE-prometheus" >/dev/null 2>&1
}

deploy() {
    choose_monitoring
    step "Deploying with Helm ($MODE mode, $PROFILE profile$([ "$MONITORING" = true ] && echo ", with monitoring"))"
    local -a args=(
        upgrade --install "$RELEASE" "$CHART"
        --create-namespace
        -f "$CHART/values-$PROFILE.yaml"
        --set "mode=$MODE"
        --set "image.repository=$IMAGE_REPO"
        --set "image.tag=$IMAGE_TAG"
        --set-file "configFile=$ROOT/config/config.yaml"
        --set "mlflow.uiUrl=http://$MLFLOW_HOST:$PORT"
        --set "monitoring.enabled=$MONITORING"
    )
    if [ -n "${ALPHA_VANTAGE_API_KEY:-}" ]; then
        args+=(--set "secrets.alphaVantageApiKey=$ALPHA_VANTAGE_API_KEY")
    fi
    h "${args[@]}" >/dev/null || die "Helm could not install the chart (see the message above)."
    wait_for_server
    ok "Release '$RELEASE' deployed (helm history $RELEASE shows every revision; helm rollback undoes one)"
}

choose_monitoring() {
    if [ -z "$MONITORING" ]; then
        if monitoring_deployed; then MONITORING=true; else MONITORING=false; fi
    fi
}

# Wait for the server only. helm --wait would also wait for the results
# volume, which is created only when the first prediction job uses it.
wait_for_server() {
    step "Waiting for the server to be ready (the first start takes a minute or two)"
    local _
    for _ in $(seq 1 60); do
        k get deployment "$RELEASE" >/dev/null 2>&1 && break
        sleep 5
    done
    if ! k rollout status "deployment/$RELEASE" --timeout "$WAIT_TIMEOUT"; then
        echo
        k get pods -o wide || true
        die "The server did not become ready. See: ./kube.sh status and ./kube.sh logs"
    fi
}

# ------------------------------------------------------------------ gitops

fx() { kubectl --context "$CONTEXT" -n flux-system "$@"; }

gitops_active() {
    fx get kustomizations.kustomize.toolkit.fluxcd.io ledger >/dev/null 2>&1
}

ensure_flux() {
    if ! have flux; then
        [ "$SYSTEM_PACKAGES" -eq 1 ] || die "Missing: flux. Install it (https://fluxcd.io), or run without --no-system-packages."
        step "Installing the Flux command line $FLUX_VERSION into ~/.local/bin"
        mkdir -p "$HOME/.local/bin"
        curl -fsSL https://fluxcd.io/install.sh | FLUX_VERSION="$FLUX_VERSION" bash -s "$HOME/.local/bin" >/dev/null
    fi
    if ! fx get deployment helm-controller >/dev/null 2>&1; then
        step "Installing Flux in the cluster (source, kustomize and helm controllers)"
        flux install --context "$CONTEXT" \
            --components=source-controller,kustomize-controller,helm-controller >/dev/null
    fi
    ok "$(flux version --client 2>/dev/null | head -1) in the cluster"
}

# Hand an existing Helm release over to Flux (the data volumes are kept)
release_to_flux() {
    if h status "$RELEASE" >/dev/null 2>&1 && ! fx get helmreleases.helm.toolkit.fluxcd.io "$RELEASE" >/dev/null 2>&1; then
        step "Handing the release over to Flux (uninstalling the Helm release; the data is kept)"
        h uninstall "$RELEASE" --wait >/dev/null
    fi
}

local_values() {
    # This cluster's own settings, merged after the image from git (HelmRelease valuesFrom)
    echo "mode: $MODE"
    echo "mlflow:"
    echo "  uiUrl: http://$MLFLOW_HOST:$PORT"
    echo "monitoring:"
    echo "  enabled: $MONITORING"
    if [ "$BUILD" -eq 1 ]; then
        echo "image:"
        echo "  repository: $GHCR_IMAGE"
        echo "  tag: \"$IMAGE_TAG\""
    fi
    if [ -n "${GHCR_TOKEN:-}" ]; then
        echo "imagePullSecrets:"
        echo "  - name: ghcr-pull"
    fi
}

deploy_gitops() {
    choose_monitoring
    release_to_flux
    kubectl --context "$CONTEXT" create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl --context "$CONTEXT" apply -f - >/dev/null
    if [ -n "${GHCR_TOKEN:-}" ]; then
        k create secret docker-registry ghcr-pull --docker-server=ghcr.io \
            --docker-username="${GHCR_USER:-$(id -un)}" --docker-password="$GHCR_TOKEN" \
            --dry-run=client -o yaml | k apply -f - >/dev/null
    fi
    local values
    values="$(mktemp)"
    local_values > "$values"
    fx create configmap ledger-profile --from-file="values.yaml=$CHART/values-$PROFILE.yaml" \
        --dry-run=client -o yaml | fx apply -f - >/dev/null
    fx create configmap ledger-local --from-file="values.yaml=$values" --dry-run=client -o yaml | fx apply -f - >/dev/null
    rm -f "$values"

    step "Pointing Flux at github.com/elyr/stock-market-predictor, branch $BRANCH"
    sed "s|^    branch: main$|    branch: $BRANCH|" "$GITOPS_FILES/flux/ledger.yaml" | kubectl --context "$CONTEXT" apply -f - >/dev/null
    flux --context "$CONTEXT" reconcile kustomization ledger --with-source --timeout 5m \
        || die "Flux could not apply deploy/gitops from GitHub. See: flux --context $CONTEXT get all -A"
    local _
    for _ in $(seq 1 30); do
        fx get helmreleases.helm.toolkit.fluxcd.io "$RELEASE" >/dev/null 2>&1 && break
        sleep 2
    done
    # Pick up this cluster's settings right away (Flux would otherwise wait for its next interval)
    flux --context "$CONTEXT" reconcile helmrelease "$RELEASE" -n flux-system --timeout "$WAIT_TIMEOUT" \
        || die "Flux could not deploy the chart. See: flux --context $CONTEXT get helmreleases -A, and ./kube.sh status"
    wait_for_server
    local tag
    tag="$(k get deployment "$RELEASE" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)"
    ok "Flux deployed $tag (git revision $(fx get gitrepositories.source.toolkit.fluxcd.io ledger -o jsonpath='{.status.artifact.revision}' 2>/dev/null | sed 's/.*://' | cut -c1-7))"
}

leave_gitops() {
    step "Switching from Flux back to Helm from this folder (the data is kept)"
    fx delete kustomizations.kustomize.toolkit.fluxcd.io ledger --wait >/dev/null 2>&1 || true
    fx delete helmreleases.helm.toolkit.fluxcd.io "$RELEASE" --wait >/dev/null 2>&1 || true
    fx delete gitrepositories.source.toolkit.fluxcd.io ledger >/dev/null 2>&1 || true
    fx delete configmap ledger-release ledger-profile ledger-local >/dev/null 2>&1 || true
}

wait_for_ingress() {
    local url="http://127.0.0.1:$PORT/api/ready" _
    for _ in $(seq 1 60); do
        curl -fsS --max-time 3 -H "Host: $HOST" "$url" >/dev/null 2>&1 && return 0
        sleep 2
    done
    return 1
}

describe_mode() {
    if [ "$MODE" = "demo" ]; then
        echo "Demo mode: simulated prices. Both dashboards fill themselves within a few minutes."
        echo "For real prices: ./kube.sh up --live"
    else
        echo "Live mode: real Yahoo Finance prices. Click \"Run analysis\" on each dashboard to start."
    fi
}

cmd_up() {
    printf '%sLedger on Kubernetes%s, %s mode, %s profile\n' "$BOLD" "$RESET" "$MODE" "$PROFILE"
    have git || install_packages git
    update_code
    ensure_tools
    ensure_cluster
    if [ -z "$GITOPS" ]; then
        if gitops_active; then GITOPS=true; else GITOPS=false; fi
    fi
    if [ "$GITOPS" = true ]; then
        ensure_flux
        if [ "$BUILD" -eq 1 ]; then
            build_image
            docker tag "$IMAGE_REPO:$IMAGE_TAG" "$GHCR_IMAGE:$IMAGE_TAG"
            k3d image import "$GHCR_IMAGE:$IMAGE_TAG" -c "$CLUSTER" >/dev/null
        fi
        deploy_gitops
    else
        [ "$BUILD" -eq 0 ] || warn "--build only matters with --gitops (without it, the image is always built here)."
        if gitops_active; then leave_gitops; fi
        build_image
        deploy
    fi
    step "Checking the app through the ingress"
    wait_for_ingress || die "The app is running but http://$HOST:$PORT does not answer. See: ./kube.sh status"
    echo
    printf '%sLedger is running at http://%s:%s%s\n' "$BOLD" "$HOST" "$PORT" "$RESET"
    echo "MLflow (training runs and model versions): http://$MLFLOW_HOST:$PORT"
    if [ "$MONITORING" = true ]; then
        echo "Grafana (dashboard): http://$GRAFANA_HOST:$PORT  |  Prometheus (metrics, alerts): http://$PROMETHEUS_HOST:$PORT"
    else
        echo "Monitoring (Prometheus and Grafana): ./kube.sh up --monitoring"
    fi
    describe_mode
    if [ "$GITOPS" = true ]; then
        echo "GitOps: Flux deploys each new image published for '$BRANCH' within minutes. Roll back by reverting the deploy commit."
    fi
    echo "Next: ./kube.sh status | ./kube.sh logs | ./kube.sh predict-now | ./kube.sh down"
    echo
    open_url "http://$HOST:$PORT"
}

# ------------------------------------------------------------- operations

cmd_status() {
    need_cluster
    step "Release"
    h status "$RELEASE" 2>/dev/null | sed -n '1,6p' || warn "Not deployed. Run ./kube.sh up"
    if gitops_active; then
        step "GitOps (Flux)"
        flux --context "$CONTEXT" get all -n flux-system 2>/dev/null | grep -v '^$' || true
    fi
    step "Pods"
    k get pods -o wide
    step "Scheduled jobs (times in their time zone)"
    k get cronjobs
    step "Recent job runs"
    k get jobs --sort-by=.metadata.creationTimestamp 2>/dev/null | tail -n 6
    step "Service and ingress"
    k get service,ingress
    step "Volumes"
    k get pvc
    echo
    local port
    port="$(cluster_port || true)"
    echo "App: http://$HOST:${port:-$PORT}"
    echo "MLflow: http://$MLFLOW_HOST:${port:-$PORT}"
    if monitoring_deployed; then
        local password
        password="$(k get secret "$RELEASE-grafana" -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d 2>/dev/null || true)"
        echo "Grafana: http://$GRAFANA_HOST:${port:-$PORT} (view without signing in; to edit: admin / ${password:-see the ledger-grafana secret})"
        echo "Prometheus: http://$PROMETHEUS_HOST:${port:-$PORT}"
    fi
}

cmd_logs() {
    need_cluster
    case "${CMD_ARG:-server}" in
        server) k logs -f "deployment/$RELEASE" ;;
        mlflow|prometheus|grafana) k logs -f "deployment/$RELEASE-${CMD_ARG}" ;;
        scans) k logs -f --prefix --max-log-requests 10 -l app.kubernetes.io/component=signal-scan ;;
        prediction) k logs -f --prefix -l app.kubernetes.io/component=daily-prediction ;;
        *) die "Unknown logs: $CMD_ARG (use server, mlflow, prometheus, grafana, scans or prediction)" ;;
    esac
}

cmd_predict_now() {
    need_cluster
    local job
    job="$RELEASE-predict-$(date +%Y%m%d-%H%M%S)"
    step "Starting job $job from the daily-prediction schedule"
    k create job "$job" --from="cronjob/$RELEASE-daily-prediction" >/dev/null
    # Follow the output once the pod starts (pulling nothing: the image is already in the cluster)
    k logs -f "job/$job" --pod-running-timeout=10m || true
    local _ succeeded failed
    for _ in $(seq 1 60); do
        succeeded="$(k get job "$job" -o jsonpath='{.status.succeeded}' 2>/dev/null)"
        failed="$(k get job "$job" -o jsonpath='{.status.failed}' 2>/dev/null)"
        [ -n "$succeeded" ] || [ -n "$failed" ] && break
        sleep 2
    done
    if [ "${succeeded:-0}" -ge 1 ]; then
        ok "Prediction finished. Copy the results with: ./kube.sh results"
    else
        die "The prediction job failed (the results, if any, are still saved). Details: kubectl --context $CONTEXT -n $NAMESPACE describe job $job"
    fi
}

cmd_results() {
    need_cluster
    local dest="${CMD_ARG:-$ROOT/results}" pod="$RELEASE-results-reader" image
    image="$(k get deployment "$RELEASE" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)" \
        || die "Ledger is not deployed. Run ./kube.sh up"
    k delete pod "$pod" --ignore-not-found --wait >/dev/null
    # A short-lived pod that mounts the results volume read-only
    k run "$pod" --image="$image" --image-pull-policy=IfNotPresent --restart=Never --quiet \
        --overrides="$(cat <<JSON
{"spec":{
  "securityContext":{"runAsNonRoot":true,"runAsUser":1000,"runAsGroup":1000,"fsGroup":1000},
  "containers":[{"name":"reader","image":"$image","command":["sleep","600"],
    "securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}},
    "volumeMounts":[{"name":"predictions","mountPath":"/predictions","readOnly":true}]}],
  "volumes":[{"name":"predictions","persistentVolumeClaim":{"claimName":"$RELEASE-predictions"}}]}}
JSON
)" >/dev/null
    # shellcheck disable=SC2064
    trap "kubectl --context '$CONTEXT' -n '$NAMESPACE' delete pod '$pod' --wait=false >/dev/null 2>&1 || true" EXIT
    k wait --for=condition=Ready "pod/$pod" --timeout=2m >/dev/null
    local day
    day="$(k exec "$pod" -- sh -c 'readlink /predictions/latest 2>/dev/null || true')"
    [ -n "$day" ] || die "No results yet. Run: ./kube.sh predict-now"
    mkdir -p "$dest/$day"
    k exec "$pod" -- tar -C "/predictions/$day" -cf - . | tar -C "$dest/$day" -xf -
    ok "Results of $day copied to $dest/$day"
    [ -f "$dest/$day/report.md" ] && echo "    Report: $dest/$day/report.md"
    return 0
}

cmd_test() {
    need_cluster
    step "Running the chart's tests"
    h test "$RELEASE" --logs --timeout 5m
    ok "Tests passed"
}

cmd_down() {
    need_cluster
    step "Uninstalling the app (the data volumes are kept)"
    # With Flux, removing its objects uninstalls the release (otherwise Flux would reinstall it)
    if gitops_active; then leave_gitops; fi
    h uninstall "$RELEASE" --wait 2>/dev/null || warn "The app was not installed."
    k get pvc 2>/dev/null || true
    ok "Done. ./kube.sh up deploys it again with the same data; ./kube.sh destroy deletes everything."
}

cmd_destroy() {
    have k3d || die "k3d is not installed, so there is no cluster to delete."
    k3d cluster get "$CLUSTER" >/dev/null 2>&1 || { ok "There is no cluster '$CLUSTER'."; return 0; }
    if [ "$ASSUME_YES" -eq 0 ]; then
        if [ ! -t 0 ]; then die "This deletes the cluster and all its data. Run with --yes to confirm."; fi
        local answer
        read -r -p "Delete the cluster '$CLUSTER' and all its data (database, models, results)? [y/N] " answer
        [[ "$answer" =~ ^[Yy] ]] || { echo "Cancelled."; return 0; }
    fi
    step "Deleting the cluster '$CLUSTER'"
    k3d cluster delete "$CLUSTER"
    ok "Deleted. Docker images built for it are kept; remove them with: docker image prune"
}

# -------------------------------------------------------------------- main

main() {
    case "$COMMAND" in
        up) cmd_up ;;
        status) cmd_status ;;
        logs) cmd_logs ;;
        predict-now) cmd_predict_now ;;
        results) cmd_results ;;
        test) cmd_test ;;
        down) cmd_down ;;
        destroy) cmd_destroy ;;
        help) usage ;;
    esac
}

# Run only when executed, not when sourced (the tests source this file)
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main
fi
