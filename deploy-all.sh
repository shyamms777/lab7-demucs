#!/bin/sh
#
# Deploy the whole system. Defaults to the GKE (Google load balancer) Ingress.
# On a local cluster with ingress-nginx instead run:
#   INGRESS=rest/rest-ingress.yaml ./deploy-all.sh
#
INGRESS=${INGRESS:-rest/rest-ingress-gke.yaml}

kubectl apply -f rustfs/rustfs-deployment.yaml
kubectl apply -f rustfs/rustfs-secret.yaml
kubectl apply -f rustfs/rustfs-external-service.yaml

kubectl apply -f redis/redis-deployment.yaml
kubectl apply -f redis/redis-service.yaml

kubectl apply -f rest/rest-deployment.yaml
kubectl apply -f rest/rest-service.yaml
kubectl apply -f "$INGRESS"

kubectl apply -f logs/logs-deployment.yaml

kubectl apply -f worker/worker-deployment.yaml
