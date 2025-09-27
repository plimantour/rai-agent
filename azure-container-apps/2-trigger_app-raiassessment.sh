#!/usr/bin/env bash
#
# Trigger a new Azure Container Apps revision for the RAI Assessment service
# after a fresh container image has been built and pushed to the registry.
#
# Prerequisites:
#   - All resources created by `1-setup_app-raiassessment.sh` already exist.
#   - You are logged in with the Azure CLI (`az login`) and targeting the
#     subscription that hosts the Container App.
#   - The new container image is available in the configured registry.
#
# Defaults can be overridden via environment variables or CLI flags:
#   CONTAINER_APP_NAME (default: app-raiassessment)
#   RESOURCE_GROUP (default: cto-containers-raiassessment-rg)
#   DOCKER_REGISTRY (default: ctodockerregistry.azurecr.io)
#   DOCKER_IMAGE (default: rai:latest)
#
# Examples:
#   DOCKER_IMAGE="rai:2025-09-27" ./2-trigger_app-raiassessment.sh
#   ./2-trigger_app-raiassessment.sh --image rai:2025-09-27 --registry ctodockerregistry.azurecr.io
#
set -euo pipefail

usage() {
    cat <<'HELP'
Trigger a new Azure Container Apps revision by updating the active container image.

Options:
  --image <repo/image:tag>     Image name (with optional registry); overrides DOCKER_IMAGE
  --registry <registry>        Container registry login server; overrides DOCKER_REGISTRY
  --container-app <name>       Container App resource name; overrides CONTAINER_APP_NAME
  --resource-group <name>      Resource group that owns the Container App; overrides RESOURCE_GROUP
  -h, --help                   Show this help message and exit

Environment variables with the same names provide defaults for each option.
HELP
}

log_section() {
    printf '\n=== %s ===\n' "$1"
}

error_exit() {
    echo "Error: $1" >&2
    exit 1
}

if ! command -v az >/dev/null 2>&1; then
    error_exit "Azure CLI is required but not found in PATH."
fi

CONTAINER_APP_NAME=${CONTAINER_APP_NAME:-app-raiassessment}
RESOURCE_GROUP=${RESOURCE_GROUP:-cto-containers-raiassessment-rg}
DOCKER_REGISTRY=${DOCKER_REGISTRY:-ctodockerregistry.azurecr.io}
DOCKER_IMAGE=${DOCKER_IMAGE:-rai:latest}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image)
            [[ $# -ge 2 ]] || error_exit "--image requires a value"
            DOCKER_IMAGE=$2
            shift 2
            ;;
        --registry)
            [[ $# -ge 2 ]] || error_exit "--registry requires a value"
            DOCKER_REGISTRY=$2
            shift 2
            ;;
        --container-app)
            [[ $# -ge 2 ]] || error_exit "--container-app requires a value"
            CONTAINER_APP_NAME=$2
            shift 2
            ;;
        --resource-group)
            [[ $# -ge 2 ]] || error_exit "--resource-group requires a value"
            RESOURCE_GROUP=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            error_exit "Unknown option: $1"
            ;;
    esac
done

log_section "Validating Azure session"
if ! az account show >/dev/null 2>&1; then
    error_exit "Run 'az login' and ensure the correct subscription is selected."
fi

log_section "Resolving container app"
if ! az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    error_exit "Container app $CONTAINER_APP_NAME not found in resource group $RESOURCE_GROUP."
fi

container_name=$(az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.template.containers[0].name" \
    --output tsv)

if [[ -z $container_name ]]; then
    error_exit "Unable to resolve container name for $CONTAINER_APP_NAME."
fi

if [[ $DOCKER_IMAGE == $DOCKER_REGISTRY* ]]; then
    full_image="$DOCKER_IMAGE"
else
    full_image="$DOCKER_REGISTRY/$DOCKER_IMAGE"
fi

log_section "Updating container app image"
latest_revision=$(az containerapp update \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --container-name "$container_name" \
    --image "$full_image" \
    --set-env-vars DEPLOY_TIME_IN_SECONDS_SINCE_EPOCH="$(date +%s)" \
    --query "properties.latestRevisionName" \
    --output tsv)

if [[ -z $latest_revision ]]; then
    error_exit "Container app update did not return a revision name."
fi

ingress_fqdn=$(az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" \
    --output tsv)

log_section "Revision triggered"
echo "Container app:      $CONTAINER_APP_NAME"
echo "Resource group:     $RESOURCE_GROUP"
echo "Container name:     $container_name"
echo "Image used:         $full_image"
echo "Latest revision:    $latest_revision"
echo "Ingress FQDN:       ${ingress_fqdn:-<ingress disabled>}"

echo
echo "Monitor rollout with:"
echo "  az containerapp revision list --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --output table"
echo "  az containerapp revision show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --revision $latest_revision"