variable "project" {
  description = "Project name used in resource naming."
  type        = string
  default     = "securecallops"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-2"
}

variable "container_image" {
  description = "Full ECR image URI including tag, such as 123456789012.dkr.ecr.eu-west-2.amazonaws.com/securecallops-dev:abc1234."
  type        = string
}

variable "postgres_admin_user" {
  description = "PostgreSQL administrator username."
  type        = string
  default     = "securecallops"
}

variable "postgres_admin_password" {
  description = "PostgreSQL administrator password."
  type        = string
  sensitive   = true
}

variable "fernet_key" {
  description = "Fernet key used to encrypt contact PII at rest."
  type        = string
  sensitive   = true
}

variable "smtp_host" {
  description = "SMTP hostname for OTP email delivery."
  type        = string
}

variable "smtp_port" {
  description = "SMTP port."
  type        = number
  default     = 587
}

variable "smtp_user" {
  description = "SMTP authentication username."
  type        = string
}

variable "smtp_password" {
  description = "SMTP authentication password."
  type        = string
  sensitive   = true
}

variable "smtp_from" {
  description = "From address for OTP emails."
  type        = string
}

variable "service_desired_count" {
  description = "Number of tasks to run per ECS service. Use 0 for the first apply before the image exists in ECR, then 1 or more after the image has been pushed."
  type        = number
  default     = 1
}
