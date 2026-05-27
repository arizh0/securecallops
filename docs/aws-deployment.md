# AWS Deployment

This repository includes a sanitized AWS deployment starter for SecureCallOps.

It is designed for ECS Fargate, RDS PostgreSQL, ECR, Secrets Manager, CloudWatch, and
GitHub Actions with OIDC.

## What It Creates

The Terraform stack in [infra/terraform-aws](../infra/terraform-aws) creates:

- A VPC with public and private subnets
- Application Load Balancers for the caller and admin services
- ECS Fargate task definitions and services
- An ECR repository for the Docker image
- An RDS PostgreSQL database
- Secrets Manager secrets for sensitive values
- CloudWatch log groups
- IAM roles for ECS task execution

No real credentials are committed. Use `terraform.tfvars.example` as a template and keep
the real `terraform.tfvars` file local or in a secure CI/CD secret store.

## Manual First Apply

The first infrastructure apply should use:

```hcl
service_desired_count = 0
```

That creates AWS resources without starting containers before the image exists in ECR.

```powershell
cd infra\terraform-aws
terraform init
terraform validate
terraform plan -var-file terraform.tfvars
terraform apply -var-file terraform.tfvars
```

After ECR exists, build and push an image, update `container_image`, set
`service_desired_count = 1`, and apply again.

## GitHub Actions Deployment

The workflow in [.github/workflows/ci.yml](../.github/workflows/ci.yml) supports AWS
deployment through GitHub OIDC. It does not use long-lived AWS access keys.

Configure these repository variables:

| Variable | Example |
| --- | --- |
| `AWS_REGION` | `eu-west-2` |
| `AWS_ROLE_TO_ASSUME` | `arn:aws:iam::123456789012:role/role-github-actions-securecallops-dev` |
| `ECR_REPOSITORY` | `securecallops-dev` |
| `ECS_CLUSTER` | `ecs-securecallops-dev` |
| `ECS_CALLER_SERVICE` | `svc-securecallops-dev-caller` |
| `ECS_ADMIN_SERVICE` | `svc-securecallops-dev-admin` |
| `CALLER_TASK_DEFINITION` | `securecallops-dev-caller` |
| `ADMIN_TASK_DEFINITION` | `securecallops-dev-admin` |

If `AWS_ROLE_TO_ASSUME` is not set, the deployment job is skipped. Tests still run.

## AWS OIDC Role

Create an IAM OIDC provider for:

```text
https://token.actions.githubusercontent.com
```

Create a role trusted by this repository and branch:

```text
repo:<owner>/<repo>:ref:refs/heads/main
```

For a fork or another repository, change `<owner>/<repo>` accordingly.

For production, scope the role permissions to only the required ECR, ECS, IAM pass-role,
and logging actions.

## Database Schema

The initial schema is in:

```text
app/sql/phonebanking_schema.sql
```

For production CI/CD, convert the schema into real migrations before automatic deployment.
The app expects database tables to exist before ECS starts new tasks.

## Security Notes

- Do not commit `terraform.tfvars`.
- Do not commit Terraform state.
- Do not use `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` for Actions if OIDC is available.
- Add HTTPS with ACM before production use.
- Move Terraform state to S3 with locking before team or CI usage.
