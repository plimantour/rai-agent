az acr login --name ctodockerregistry
../docker_build_image.sh
docker push ctodockerregistry.azurecr.io/rai:latest
./1-setup_app-raiassessment.sh
echo "Podcast Anything app rebuilt and deployed"
