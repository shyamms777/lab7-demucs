VERSION=v1
DOCKERUSER=YOUR_DOCKER_USERNAME_HERE

build:
	docker build -f Dockerfile -t demucs-worker .
push:
	docker tag demucs-worker $(DOCKERUSER)/demucs-worker:$(VERSION)
	docker push $(DOCKERUSER)/demucs-worker:$(VERSION)
	docker tag demucs-worker $(DOCKERUSER)/demucs-worker:latest
	docker push $(DOCKERUSER)/demucs-worker:latest

#
# Google Cloud: build with Cloud Build and push to Artifact Registry.
# The 3.5 GB base image is pulled inside Google's network, not Cloud Shell.
#   make cloud              -> .../lab7/demucs-worker:$(VERSION)
#   make cloud VERSION=dev
#
REGION ?= us-central1
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
REPO ?= $(REGION)-docker.pkg.dev/$(PROJECT)/lab7

cloud:
	gcloud builds submit . --tag $(REPO)/demucs-worker:$(VERSION) --timeout=45m
