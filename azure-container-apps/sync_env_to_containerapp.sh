#!/usr/bin/env bash
# Sync environment variables from a local .env file to an Azure Container App.
#
# Defaults align with the RAI Assessment deployment defined in this repository.
# Usage examples:
#   ./sync_env_to_containerapp.sh                       # push ./.env to default app
#   ./sync_env_to_containerapp.sh --dry-run             # show planned changes only
#   ./sync_env_to_containerapp.sh --env-file .env.prod  # use alternate env file
#   ./sync_env_to_containerapp.sh --exclude AZURE_OPENAI_API_KEY
#
set -euo pipefail

usage() {
    cat <<'EOF'
Synchronize key/value pairs from a .env file into an Azure Container App.

Options:
  --env-file <path>         Path to env file (default: ../.env)
  --container-app <name>    Container App name (default: app-raiassessment)
  --resource-group <name>   Resource group (default: cto-containers-raiassessment-rg)
  --exclude <k1,k2,...>     Comma-separated variable names to skip
  --dry-run                 Show actions without calling Azure CLI
  --prune                   Remove container app variables not present in the env file
  -h, --help                Show this help message
EOF
}

error_exit() {
    echo "Error: $1" >&2
    exit 1
}

require_az() {
    if ! command -v az >/dev/null 2>&1; then
        error_exit "Azure CLI (az) is required in PATH."
    fi
}

trim() {
    local s="$1"
    # shellcheck disable=SC2001
    s="$(echo "$s" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    printf '%s' "$s"
}

strip_quotes() {
    local value="$1"
    if [[ ${#value} -ge 2 ]]; then
        local first="${value:0:1}" last="${value: -1}"
        if [[ "$first" == '"' && "$last" == '"' ]]; then
            value="${value:1:-1}"
            value="${value//\\"/"}"
        elif [[ "$first" == "'" && "$last" == "'" ]]; then
            value="${value:1:-1}"
        fi
    fi
    printf '%s' "$value"
}

split_excludes() {
    local raw="$1"
    IFS=',' read -ra EXCLUDES <<<"$raw"
    for item in "${EXCLUDES[@]}"; do
        local key
        key="$(trim "$item")"
        if [[ -n "$key" ]]; then
            exclude_lookup["$key"]=1
        fi
    done
}

ENV_FILE="../.env"
CONTAINER_APP_NAME=${CONTAINER_APP_NAME:-app-raiassessment}
RESOURCE_GROUP=${RESOURCE_GROUP:-cto-containers-raiassessment-rg}
DRY_RUN=false
PRUNE=false

declare -A exclude_lookup=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file)
            [[ $# -ge 2 ]] || error_exit "--env-file requires a value"
            ENV_FILE=$2
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
        --exclude)
            [[ $# -ge 2 ]] || error_exit "--exclude requires a value"
            split_excludes "$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --prune)
            PRUNE=true
            shift
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

require_az

if [[ ! -f "$ENV_FILE" ]]; then
    error_exit "Env file '$ENV_FILE' not found"
fi

if ! az account show >/dev/null 2>&1; then
    error_exit "Azure CLI is not logged in; run 'az login' first."
fi

if ! az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    error_exit "Container App $CONTAINER_APP_NAME not found in resource group $RESOURCE_GROUP."
fi

declare -A env_map=()
declare -a env_order=()

while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="$(trim "$raw_line")"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" == export* ]]; then
        line="$(trim "${line#export}")"
    fi
    if [[ "$line" != *=* ]]; then
        echo "Skipping malformed line: $raw_line" >&2
        continue
    fi
    key="${line%%=*}"
    key="$(trim "$key")"
    value="${line#*=}"
    value="$(trim "$value")"

    # Strip trailing inline comment starting with unescaped #
    if [[ "$value" == *' #'* ]]; then
        value="${value%% #[![:space:]]*}"
        value="$(trim "$value")"
    fi

    value="$(strip_quotes "$value")"

    if [[ -z "$key" ]]; then
        continue
    fi
    if [[ -n "${exclude_lookup[$key]:-}" ]]; then
        continue
    fi
    # Ensure key matches shell-style env var format
    if [[ ! $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        echo "Skipping unsupported key '$key'" >&2
        continue
    fi

    if [[ -z "${env_map[$key]+_}" ]]; then
        env_order+=("$key")
    fi
    env_map["$key"]="$value"

done <"$ENV_FILE"

if [[ ${#env_order[@]} -eq 0 ]]; then
    error_exit "No environment variables parsed from $ENV_FILE"
fi

declare -a env_pairs=()
for key in "${env_order[@]}"; do
    env_pairs+=("$key=${env_map[$key]}")

done

if $DRY_RUN; then
    echo "[DRY-RUN] Container app: $CONTAINER_APP_NAME (resource group: $RESOURCE_GROUP)"
    echo "[DRY-RUN] Env file: $ENV_FILE"
    echo "[DRY-RUN] Variables to upsert:"
    for pair in "${env_pairs[@]}"; do
        var_name="${pair%%=*}"
        echo "  - $var_name"
    done
    if $PRUNE; then
        echo "[DRY-RUN] --prune: would remove variables missing from $ENV_FILE"
    fi
    exit 0
fi

update_cmd=(az containerapp update --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" --set-env-vars)
update_cmd+=("${env_pairs[@]}")

printf 'Applying %d environment variables to %s...\n' "${#env_pairs[@]}" "$CONTAINER_APP_NAME"
"${update_cmd[@]}" >/dev/null

echo "Environment variables synchronized."

if $PRUNE; then
    existing_keys=$(az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.template.containers[0].env[].name" \
        --output tsv)

    declare -A keep_lookup=()
    for key in "${env_order[@]}"; do
        keep_lookup["$key"]=1
    done

    declare -a remove_keys=()
    while IFS= read -r item; do
        [[ -z "$item" ]] && continue
        if [[ -z "${keep_lookup[$item]:-}" ]]; then
            remove_keys+=("$item")
        fi
    done <<<"$existing_keys"

    if [[ ${#remove_keys[@]} -gt 0 ]]; then
        remove_cmd=(az containerapp update --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" --remove-env-vars)
        remove_cmd+=("${remove_keys[@]}")
        printf 'Pruning %d variables from %s...\n' "${#remove_keys[@]}" "$CONTAINER_APP_NAME"
        "${remove_cmd[@]}" >/dev/null
        echo "Prune completed."
    else
        echo "No variables to prune."
    fi
fi
