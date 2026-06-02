# GCP GKE Deployment

This deployment runs SecureCallOps privately on Google Kubernetes Engine.

Current scope:

- Artifact Registry stores the Docker image.
- GKE Autopilot runs the caller and admin services.
- Cloud SQL for PostgreSQL stores application data.
- Cloud SQL uses private IP.
- Pods connect to Cloud SQL through the Cloud SQL Auth Proxy sidecar.
- The app is tested with `kubectl port-forward`.

Not included yet:

- Public static IP
- DNS records
- Managed HTTPS certificate
- Kubernetes Ingress
- GitHub Actions CI/CD
- Terraform-managed infrastructure

## Why This Scope

This is the first Kubernetes milestone.

The goal is to prove that the app can run in GKE and connect to a private
database before adding public routing or CI/CD.

## Architecture

```text
browser
  -> kubectl port-forward
  -> Kubernetes Service
  -> SecureCallOps Pod
  -> Cloud SQL Auth Proxy sidecar
  -> private Cloud SQL PostgreSQL
```

## Kubernetes Objects

The Kubernetes template is in:

```text
infra/gke/securecallops-gke.yaml
```

It creates:

- `Namespace`: `securecallops`
- `Deployment`: `caller`
- `Deployment`: `admin`
- `Service`: `caller`
- `Service`: `admin`

Create these manually for the first deployment:

- `ConfigMap`: `securecallops-config`
- `Secret`: `securecallops-secrets`
- `ServiceAccount`: `securecallops-runtime`

## Suggested GCP Resources

For a first private deployment, create:

- VPC and GKE subnet with secondary ranges for Pods and Services
- Private services access for Cloud SQL private IP
- Artifact Registry Docker repository
- Cloud SQL PostgreSQL instance with private IP only
- GKE Autopilot cluster
- GCP IAM service account for the Pods
- Workload Identity Federation for GKE
- Secret Manager secrets for sensitive values

## Terraform Note

Terraform is the right long-term improvement for repeatable infrastructure.

For a first learning deployment, creating infrastructure manually with
`gcloud.cmd` can be useful because each resource is easier to understand.

If Terraform is added after manual resources already exist, either:

1. Import the existing GCP resources into Terraform state.
2. Destroy and recreate the dev environment from Terraform.

Do not create Terraform for resources that already exist without planning the
import or replacement path. That can cause naming conflicts or accidental
duplicate infrastructure.
