VERSION=v1
DOCKERUSER=YOUR_DOCKER_USERNAME_HERE

build:
	docker build -f Dockerfile-rest -t demucs-rest .

push:
	docker tag demucs-rest $(DOCKERUSER)/demucs-rest:$(VERSION)
	docker push $(DOCKERUSER)/demucs-rest:$(VERSION)
	docker tag demucs-rest $(DOCKERUSER)/demucs-rest:latest
	docker push $(DOCKERUSER)/demucs-rest:latest

#
# Google Cloud: build with Cloud Build and push to Artifact Registry.
#   make cloud              -> .../lab7/demucs-rest:$(VERSION)
#   make cloud VERSION=v2
#
REGION ?= us-central1
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
REPO ?= $(REGION)-docker.pkg.dev/$(PROJECT)/lab7

cloud:
	gcloud builds submit . --config cloudbuild.yaml --substitutions=_IMAGE=$(REPO)/demucs-rest:$(VERSION)
