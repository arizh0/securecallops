terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name = "${var.project}-${var.environment}"

  common_tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(local.common_tags, { Name = "vpc-${local.name}" })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "igw-${local.name}" })
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet("10.0.0.0/16", 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
  tags                    = merge(local.common_tags, { Name = "subnet-public-${count.index}-${local.name}" })
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet("10.0.0.0/16", 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags              = merge(local.common_tags, { Name = "subnet-private-${count.index}-${local.name}" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(local.common_tags, { Name = "rt-public-${local.name}" })
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "eip-nat-${local.name}" })
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = merge(local.common_tags, { Name = "nat-${local.name}" })
  depends_on    = [aws_internet_gateway.main]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = merge(local.common_tags, { Name = "rt-private-${local.name}" })
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "alb" {
  name        = "sgrp-alb-${local.name}"
  description = "Allow HTTP and HTTPS inbound to ALBs"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "sgrp-alb-${local.name}" })
}

resource "aws_security_group" "ecs" {
  name        = "sgrp-ecs-${local.name}"
  description = "Allow inbound from ALB only"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 8001
    to_port         = 8002
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "sgrp-ecs-${local.name}" })
}

resource "aws_security_group" "rds" {
  name        = "sgrp-rds-${local.name}"
  description = "Allow PostgreSQL inbound from ECS only"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  tags = merge(local.common_tags, { Name = "sgrp-rds-${local.name}" })
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_secretsmanager_secret" "postgres_password" {
  name                    = "${local.name}/postgres-password"
  recovery_window_in_days = 0
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "postgres_password" {
  secret_id     = aws_secretsmanager_secret.postgres_password.id
  secret_string = var.postgres_admin_password
}

resource "aws_secretsmanager_secret" "fernet_key" {
  name                    = "${local.name}/fernet-key"
  recovery_window_in_days = 0
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "fernet_key" {
  secret_id     = aws_secretsmanager_secret.fernet_key.id
  secret_string = var.fernet_key
}

resource "aws_secretsmanager_secret" "smtp_password" {
  name                    = "${local.name}/smtp-password"
  recovery_window_in_days = 0
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "smtp_password" {
  secret_id     = aws_secretsmanager_secret.smtp_password.id
  secret_string = var.smtp_password
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "role-ecs-exec-${local.name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_base" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_secrets" {
  name = "policy-ecs-secrets-${local.name}"
  role = aws_iam_role.ecs_task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.postgres_password.arn,
        aws_secretsmanager_secret.fernet_key.arn,
        aws_secretsmanager_secret.smtp_password.arn,
      ]
    }]
  })
}

resource "aws_iam_role" "ecs_task" {
  name = "role-ecs-task-${local.name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })

  tags = local.common_tags
}

resource "aws_ecs_cluster" "main" {
  name = "ecs-${local.name}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "caller" {
  name              = "/ecs/${local.name}/caller"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "admin" {
  name              = "/ecs/${local.name}/admin"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_db_subnet_group" "main" {
  name       = "dbsg-${local.name}"
  subnet_ids = aws_subnet.private[*].id
  tags       = merge(local.common_tags, { Name = "dbsg-${local.name}" })
}

resource "aws_db_instance" "main" {
  identifier              = "rds-${local.name}"
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  db_name                 = var.project
  username                = var.postgres_admin_user
  password                = var.postgres_admin_password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  skip_final_snapshot     = true
  backup_retention_period = 7
  storage_encrypted       = true
  tags                    = local.common_tags
}

locals {
  app_env = [
    { name = "OPS_DB_USER", value = var.postgres_admin_user },
    { name = "OPS_DB_NAME", value = var.project },
    { name = "OPS_DB_HOST", value = aws_db_instance.main.address },
    { name = "OPS_DB_PORT", value = "5432" },
    { name = "OPS_DB_SSLMODE", value = "require" },
    { name = "OPS_DB_POOL_MIN", value = "1" },
    { name = "OPS_DB_POOL_MAX", value = "10" },
    { name = "COOKIE_SECURE", value = "true" },
    { name = "SMTP_HOST", value = var.smtp_host },
    { name = "SMTP_PORT", value = tostring(var.smtp_port) },
    { name = "SMTP_USER", value = var.smtp_user },
    { name = "SMTP_FROM", value = var.smtp_from },
  ]

  secret_env = [
    { name = "OPS_DB_PASS", valueFrom = aws_secretsmanager_secret.postgres_password.arn },
    { name = "FERNET_KEY", valueFrom = aws_secretsmanager_secret.fernet_key.arn },
    { name = "SMTP_PASS", valueFrom = aws_secretsmanager_secret.smtp_password.arn },
  ]
}

resource "aws_ecs_task_definition" "caller" {
  family                   = "${local.name}-caller"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "caller"
    image     = var.container_image
    essential = true

    portMappings = [{ containerPort = 8001, protocol = "tcp" }]

    environment = concat(local.app_env, [
      { name = "APP_MODULE", value = "app.phonebanking.main:app" },
      { name = "PORT", value = "8001" },
    ])

    secrets = local.secret_env

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.caller.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "admin" {
  family                   = "${local.name}-admin"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "admin"
    image     = var.container_image
    essential = true

    portMappings = [{ containerPort = 8002, protocol = "tcp" }]

    environment = concat(local.app_env, [
      { name = "APP_MODULE", value = "app.admin.main:app" },
      { name = "PORT", value = "8002" },
    ])

    secrets = local.secret_env

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.admin.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = local.common_tags
}

resource "aws_lb" "caller" {
  name               = "alb-${local.name}-caller"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  tags               = merge(local.common_tags, { Name = "alb-${local.name}-caller" })
}

resource "aws_lb_target_group" "caller" {
  name        = "tg-${local.name}-caller"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/pb/login"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "caller" {
  load_balancer_arn = aws_lb.caller.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.caller.arn
  }
}

resource "aws_lb" "admin" {
  name               = "alb-${local.name}-admin"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  tags               = merge(local.common_tags, { Name = "alb-${local.name}-admin" })
}

resource "aws_lb_target_group" "admin" {
  name        = "tg-${local.name}-admin"
  port        = 8002
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/login"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "admin" {
  load_balancer_arn = aws_lb.admin.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.admin.arn
  }
}

resource "aws_ecs_service" "caller" {
  name            = "svc-${local.name}-caller"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.caller.arn
  desired_count   = var.service_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.caller.arn
    container_name   = "caller"
    container_port   = 8001
  }

  depends_on = [
    aws_lb_listener.caller,
    aws_iam_role_policy_attachment.ecs_task_execution_base,
  ]

  tags = local.common_tags
}

resource "aws_ecs_service" "admin" {
  name            = "svc-${local.name}-admin"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.admin.arn
  desired_count   = var.service_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.admin.arn
    container_name   = "admin"
    container_port   = 8002
  }

  depends_on = [
    aws_lb_listener.admin,
    aws_iam_role_policy_attachment.ecs_task_execution_base,
  ]

  tags = local.common_tags
}
