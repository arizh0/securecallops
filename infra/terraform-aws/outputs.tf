output "caller_url" {
  description = "Public URL for the caller service."
  value       = "http://${aws_lb.caller.dns_name}"
}

output "admin_url" {
  description = "Public URL for the admin service."
  value       = "http://${aws_lb.admin.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR repository URL for application images."
  value       = aws_ecr_repository.app.repository_url
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint hostname."
  value       = aws_db_instance.main.address
}
