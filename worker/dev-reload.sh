#!/bin/sh
#
# Push your edited worker-server.py into the cluster and restart the worker.
# Only works while worker/worker-dev-deployment.yaml is the active deployment.
#
#   ./worker/dev-reload.sh
#
set -e
kubectl create configmap worker-code --from-file=worker/worker-server.py \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/worker
kubectl rollout status deployment/worker --timeout=300s
echo "worker restarted; follow it with: kubectl logs -f deploy/worker"
