variable "db_password" {
  description = "Master password for the RDS PostgreSQL database"
  type        = string
  sensitive   = true
}

variable "jwt_secret" {
  description = "JWT signing secret for the application"
  type        = string
  sensitive   = true
}

variable "github_org" {
  description = "GitHub username or organization that owns frontend and backend"
  type        = string
  default     = "dpk-zenpharma"
}

variable "github_owner_id" {
  description = "Numeric GitHub owner ID for the frontend repository"
  type        = string
}

variable "github_frontend_repository_id" {
  description = "Numeric GitHub repository ID for the frontend repository"
  type        = string
}
