# SecureCallOps AWS Terraform

Terraform configuration for running SecureCallOps on AWS ECS Fargate.

This stack creates the network, database, container runtime, load balancers, logs, and
secrets needed to run the caller and admin services on AWS.

## Resources

| Resource | Purpose |
| --- | --- |
| VPC, public subnets, private subnets, route tables | Network boundary for the stack |
| Internet Gateway and NAT Gateway | Public ALB access and private task egress |
| Security groups | ALB to ECS to RDS traffic flow |
| ECR repository | Container image storage |
| Secrets Manager secrets | Database password, Fernet key, and SMTP password |
| IAM roles and policies | ECS task execution, secret access, and logging |
| ECS cluster, task definitions, and services | Fargate runtime for caller and admin apps |
| Application Load Balancers | Public HTTP endpoints for both services |
| CloudWatch log groups | Container log retention |
| RDS PostgreSQL 16 | Managed application database |

## Configuration

Create a local variables file:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
```

Fill in every `CHANGE_ME` value. `terraform.tfvars` is ignored by Git because it contains
credentials.

For the first apply, keep:

```hcl
service_desired_count = 0
```

This creates the infrastructure and ECR repository without starting ECS tasks before the
image exists.

## Deploy

```powershell
terraform init
terraform validate
terraform plan -var-file terraform.tfvars
terraform apply -var-file terraform.tfvars
```

Push an image to the `ecr_repository_url` output, then update `container_image`, set
`service_desired_count = 1`, and apply again.

For CI/CD setup, see [../../docs/aws-deployment.md](../../docs/aws-deployment.md).

## Production Notes

This is a development-oriented starter. Before production use, add or review:

- HTTPS listeners and ACM certificates
- Remote Terraform state with locking
- Automated database migrations
- GitHub Actions OIDC with least-privilege IAM
- VPC endpoints for ECR, Secrets Manager, and CloudWatch
- Backups, restore testing, monitoring, and alerting
