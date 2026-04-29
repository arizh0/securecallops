variable "project" {
  description = "Project name used for Azure resource naming."
  type        = string
  default     = "securecallops"
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "uksouth"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"
}

variable "container_image" {
  description = "Container image to run for both SecureCallOps services."
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

variable "allow_azure_services_to_postgres" {
  description = "Demo-only escape hatch that adds the Azure-services PostgreSQL firewall rule. Prefer private networking for real data."
  type        = bool
  default     = false
}

variable "fernet_key" {
  description = "Fernet key used to encrypt contact PII."
  type        = string
  sensitive   = true
}

variable "smtp_host" {
  description = "SMTP host for OTP delivery."
  type        = string
}

variable "smtp_port" {
  description = "SMTP port for OTP delivery."
  type        = number
  default     = 587
}

variable "smtp_user" {
  description = "SMTP username."
  type        = string
}

variable "smtp_password" {
  description = "SMTP password."
  type        = string
  sensitive   = true
}

variable "smtp_from" {
  description = "From address for OTP emails."
  type        = string
}
