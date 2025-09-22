SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR"
docker build --build-arg BUILD_TIME="$(date '+%d/%m/%Y %Hh%M')" -t ctodockerregistry.azurecr.io/rai . 
