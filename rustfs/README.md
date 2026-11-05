# RustFS object storage

MinIO is no longer supported, so this lab stores songs and separated tracks in
[RustFS](https://github.com/rustfs/rustfs), an S3-compatible object store
written in Rust. It follows the course tutorial
[06-rustfs](https://github.com/cu-csci-4253-datacenter/kubernetes-tutorial/tree/master/06-rustfs):
the same namespace (`rustfs-ns`), ports (9000 S3 API, 9001 console) and demo
credentials.

The tutorial installs RustFS with Helm. These files deploy the same official
image (`rustfs/rustfs:1.0.4`) with plain YAML instead, so no Helm install is
needed:

| File | What it creates |
|---|---|
| `rustfs-deployment.yaml` | Namespace `rustfs-ns`, Secret `rustfs-creds`, a 2 GiB PersistentVolumeClaim, the RustFS Deployment, and Service `rustfs` |
| `rustfs-secret.yaml` | A copy of `rustfs-creds` in `default`, for the rest and worker pods |
| `rustfs-external-service.yaml` | Alias `rustfs` in `default` → `rustfs.rustfs-ns.svc.cluster.local` |

```sh
kubectl apply -f rustfs/
kubectl get pods,svc,pvc -n rustfs-ns
```

The rest and worker servers use two buckets, created on first use:

- `queue`: uploaded songs waiting to be separated, named `<songhash>.mp3`
- `output`: separated tracks, named `<songhash>-<track>.mp3`

They talk to RustFS with the `minio` Python package, which is a general S3
client and works with any S3-compatible server. Settings come from
`S3_HOST`, `S3_ACCESS_KEY` and `S3_SECRET_KEY`.

To browse the buckets, run
`kubectl port-forward -n rustfs-ns svc/rustfs 9000:9000 9001:9001`
and open http://localhost:9001 (access key `rustfs-lab-user`, secret
`replace-this-demo-secret`).
