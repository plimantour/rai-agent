az acr login --name ctodockerregistry
../docker_build_image.sh
docker push ctodockerregistry.azurecr.io/rai:latest
./2-trigger_app-raiassessment.sh --image rai:latest
echo "Podcast Anything app rebuilt and deployed"
