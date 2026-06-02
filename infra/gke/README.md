# SecureCallOps GKE Manifests

This folder contains a Kubernetes manifest template for a first GCP/GKE
deployment.

This deployment is intentionally private:

```text
browser
  -> kubectl port-forward
  -> Kubernetes Service
  -> SecureCallOps Pod
  -> Cloud SQL Auth Proxy sidecar
  -> private Cloud SQL PostgreSQL
```

It does not create public HTTPS, DNS, ManagedCertificate, or Ingress yet.

## Before Applying

Replace these placeholders in `securecallops-gke.yaml`:

| Placeholder | Value |
| --- | --- |
| `IMAGE_REPLACE_ME` | Full Artifact Registry image URI |
| `INSTANCE_CONNECTION_NAME_REPLACE_ME` | Cloud SQL connection name |

Example image:

```text
europe-west2-docker.pkg.dev/PROJECT_ID/securecallops-dev/securecallops:bootstrap
```

Example Cloud SQL connection name:

```text
PROJECT_ID:europe-west2:pg-securecallops-dev
```

## Required Kubernetes Objects

Create these before applying the manifest:

- Namespace: `securecallops`
- ServiceAccount: `securecallops-runtime`
- ConfigMap: `securecallops-config`
- Secret: `securecallops-secrets`

The service account should be linked to a GCP IAM service account that has
`roles/cloudsql.client`.

## Apply

```powershell
kubectl apply -f infra\gke\securecallops-gke.yaml
```

## Check

```powershell
kubectl get deployments --namespace=securecallops
kubectl get pods --namespace=securecallops
kubectl get services --namespace=securecallops
```

## Test Privately

Caller:

```powershell
kubectl port-forward service/caller 8001:80 --namespace=securecallops
```

Open:

```text
http://localhost:8001/pb/login
```

Admin:

```powershell
kubectl port-forward service/admin 8002:80 --namespace=securecallops
```

Open:

```text
http://localhost:8002/login
```
