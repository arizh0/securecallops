# SecureCallOps Azure Terraform Starter

This directory contains a minimal Azure example for running SecureCallOps with Terraform.

Secrets are passed in as variables so you can connect them to your own CI/CD setup or Key Vault flow. Terraform state can contain secret values, so use a protected remote backend before using real credentials.

## What It Creates

- Resource group
- Log Analytics workspace
- Azure Container Registry
- User-assigned managed identity with `AcrPull`
- Azure Database for PostgreSQL Flexible Server
- PostgreSQL database
- Key Vault and secret placeholders
- Azure Container Apps environment
- Admin Container App
- Caller Container App

## Usage

```powershell
terraform init
terraform plan -var-file="terraform.tfvars"
terraform apply -var-file="terraform.tfvars"
```

Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in real values. Do not commit `terraform.tfvars`.

Terraform creates the registry and grants Container Apps permission to pull from it, but it does not build or push an image. Build and push `securecallops` to the created ACR before the first successful app rollout.

## Notes

- Run the SQL schema separately after PostgreSQL is created.
- PostgreSQL is not opened to all Azure services by default. Set `allow_azure_services_to_postgres = true` only for a short-lived demo, or add private networking before using real data.
- For production, add private networking, stricter firewall rules, GitHub Actions OIDC, and a locked-down remote Terraform backend.
