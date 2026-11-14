variable "project" {
  description = "Project name"
  type        = string
}

variable "env" {
  description = "Environment name (dev, qa, prod)"
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS OIDC provider"
  type        = string
}

variable "oidc_provider_url" {
  description = "URL of the EKS OIDC provider"
  type        = string
}

variable "aws_account_id" {
  description = "AWS Account ID"
  type        = string
}

variable "github_org" {
  description = "GitHub organization or username that owns frontend and backend"
  type        = string
}

variable "github_owner_id" {
  description = "Numeric GitHub owner ID for the frontend repository"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must contain only digits."
  }
}

variable "github_frontend_repository_id" {
  description = "Numeric GitHub repository ID for the frontend repository"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_frontend_repository_id))
    error_message = "github_frontend_repository_id must contain only digits."
  }
}
