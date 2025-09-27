SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR"
docker build \
	--build-arg BUILD_TIME="$(date '+%d/%m/%Y %Hh%M')" \
	--build-arg STATIC_ASSET_VERSION="$(date +%s)" \
	-t ctodockerregistry.azurecr.io/rai . 
