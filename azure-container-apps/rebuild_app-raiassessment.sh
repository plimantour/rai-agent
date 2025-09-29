az acr login --name ctodockerregistry

../docker_build_image.sh

docker push ctodockerregistry.azurecr.io/rai:latest

echo "Synching environment variables to the container app"
./sync_env_to_containerapp.sh

echo "Triggering new container app revision"
./2-trigger_app-raiassessment.sh --image rai:latest

echo "Podcast Anything app rebuilt and deployed"
