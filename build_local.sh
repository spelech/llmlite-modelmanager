#!/bin/bash
# Local build and push to registry on 8003

VERSION=$(cat VERSION)
IMAGE="localhost:8003/llmlite-modelmanager"

echo "Building version $VERSION..."
docker build -t $IMAGE:latest -t $IMAGE:$VERSION .

echo "Pushing to local registry..."
docker push $IMAGE:latest
docker push $IMAGE:$VERSION

echo "Done. Update your docker-compose.yaml to use $IMAGE:latest"
