output "db_instance_endpoint" {
  description = "Connection endpoint for the RDS instance (hostname:port)"
  value       = module.rds.db_instance_endpoint
}

output "db_instance_address" {
  description = "Hostname of the RDS instance (without port)"
  value       = module.rds.db_instance_address
}

output "db_instance_port" {
  description = "Port of the RDS instance"
  value       = module.rds.db_instance_port
}

output "db_instance_name" {
  description = "Name of the database"
  value       = module.rds.db_instance_name
}