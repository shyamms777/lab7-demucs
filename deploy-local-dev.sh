#!/bin/sh
#
# Launch ONLY the infrastructure (RustFS, Redis, logs) on Kubernetes and
# forward their ports to your computer. Then run rest-server.py and
# worker-server.py directly on your laptop -- no image rebuilds while coding.
#
# To stop the port-forwards later:  pkill -f port-forward   (or close the shell)
#
kubectl apply -f rustfs/rustfs-deployment.yaml
kubectl apply -f rustfs/rustfs-secret.yaml
kubectl apply -f rustfs/rustfs-external-service.yaml

kubectl apply -f redis/redis-deployment.yaml
kubectl apply -f redis/redis-service.yaml

kubectl apply -f logs/logs-deployment.yaml

echo "waiting for pods to be ready..."
kubectl wait --for=condition=available deployment/redis --timeout=120s
kubectl wait -n rustfs-ns --for=condition=available deployment/rustfs --timeout=180s

kubectl port-forward --address 0.0.0.0 service/redis 6379:6379 &
kubectl port-forward -n rustfs-ns --address 0.0.0.0 service/rustfs 9000:9000 9001:9001 &
wait
