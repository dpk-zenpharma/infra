output "repository_urls" {
  description = "Map of repository name to repository URL"
  value       = { for name, repo in aws_ecr_repository.main : name => repo.repository_url }
}