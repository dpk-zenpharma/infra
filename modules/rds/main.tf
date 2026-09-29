resource "aws_security_group" "rds" {
  name        = "${var.project}-${var.env}-rds-sg"
  description = "Security group for RDS PostgreSQL instance"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from EKS worker nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.eks_node_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project}-${var.env}-rds-sg"
    Project = var.project
    Env     = var.env
  }
}

module "rds" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 7.0"

  identifier = "${var.project}-${var.env}-postgres"

  engine               = "postgres"
  engine_version       = "17.9"
  family               = "postgres17"
  major_engine_version = "17"
  instance_class       = var.instance_class

  allocated_storage = var.allocated_storage
  storage_type      = "gp3"

  db_name                     = var.db_name
  username                    = var.username
  manage_master_user_password = false
  password_wo                 = var.password
  password_wo_version         = var.password_version

  multi_az               = var.multi_az
  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = [aws_security_group.rds.id]

  skip_final_snapshot     = var.skip_final_snapshot
  backup_retention_period = var.backup_retention_period
  storage_encrypted       = true
  deletion_protection     = var.deletion_protection
  publicly_accessible     = false

  create_db_option_group = false

  tags = {
    Name    = "${var.project}-${var.env}-postgres"
    Project = var.project
    Env     = var.env
  }
}