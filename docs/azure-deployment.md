# Azure Deployment Notes

The Terraform in `infra/terraform` is a starter, not a turnkey production setup. Review it before using it with real contact data.

## Target Architecture

- Azure Container Registry stores the Docker image.
- Azure Container Apps runs separate admin and caller apps.
- A managed identity pulls images from Azure Container Registry.
- Azure Database for PostgreSQL Flexible Server stores application data.
- Azure Key Vault stores application secrets.
- Log Analytics receives platform logs.
- GitHub Actions can build/test on pull requests and can be extended for OIDC-based Azure deployment.

## Production Hardening

- GitHub Actions OIDC with Azure federated credentials is safer than long-lived client secrets.
- Put PostgreSQL on a private network and restrict firewall rules to deployment and runtime subnets.
- The Terraform disables the broad Azure-services firewall rule by default. Only flip `allow_azure_services_to_postgres` for a short demo.
- Keep `FERNET_KEY`, the SMTP password, and the database password in Key Vault, not in app settings.
- Turn on PostgreSQL backups and test a restore before it matters.
- Set Container Apps log retention to match whatever privacy requirements apply.
- An ingress or WAF layer is worth adding if the app is publicly reachable.
- Alert on repeated OTP failures, admin exports, and unexpected upload spikes.

## Deployment Flow

1. Apply Terraform once to create the registry and supporting resources.
2. Build and push an image to the created Azure Container Registry.
3. Re-apply Terraform with `container_image` set to the pushed image.
4. Run the SQL schema against PostgreSQL.
5. Seed the first admin:

```sql
INSERT INTO pb_admin_users(email) VALUES ('you@example.com');
```

6. Configure SMTP credentials and test OTP delivery.
7. Upload sanitized test contacts before using any real data.

## CI/CD Direction

The included `.github/workflows/ci.yml` runs Python checks and builds the Docker image. A real deployment workflow should add:

- Azure login via OIDC.
- ACR image build and push.
- Terraform plan on pull requests, apply only after approval.
- Container Apps revision rollout.
- Post-deployment smoke checks against a known endpoint.
