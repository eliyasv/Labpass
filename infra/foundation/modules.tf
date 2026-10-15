locals {
  application_components = toset(["api", "relay", "bootstrap", "migration"])
  # Frontend owns origin TLS when enabled; standalone hosting supplies its certificate.
  listener_certificate_arn = var.application == null ? null : (
    var.frontend == null ? var.application.origin_certificate_arn : module.frontend.certificates["origin"]
  )
}

# Establish subnet boundaries used by every private workload.
module "network" {
  source      = "../modules/network"
  name_prefix = var.name_prefix
  aws_region  = var.aws_region
}

# Own RDS, database credentials and the client identities used by application components.
module "database" {
  source                       = "../modules/database"
  name_prefix                  = var.name_prefix
  database_engine_version      = var.database_engine_version
  database_deletion_protection = var.database_deletion_protection
  vpc_id                       = module.network.network.vpc_id
  database_subnet_ids          = module.network.network.database_subnet_ids
  queue_arn                    = aws_sqs_queue.confirmations.arn
}

# Connect the API/relay fleets and database operator hosts to shared services.
module "application" {
  source         = "../modules/application"
  name_prefix    = var.name_prefix
  aws_account_id = var.aws_account_id
  aws_region     = var.aws_region
  application = var.application == null ? null : {
    ami_id                 = var.application.ami_id
    image_digest           = var.application.image_digest
    public_origin          = var.application.public_origin
    api_desired_capacity   = var.application.api_desired_capacity
    relay_desired_capacity = var.application.relay_desired_capacity
  }
  origin_verify_token          = var.origin_verify_token
  origin_verify_previous_token = var.origin_verify_previous_token
  listener_certificate_arn     = local.listener_certificate_arn
  vpc_id                       = module.network.network.vpc_id
  public_subnet_ids            = module.network.network.public_subnet_ids
  application_subnet_ids       = module.network.network.application_subnet_ids
  # Bootstrap needs master and role-secret references to create restricted database users.
  database = {
    host              = module.database.database.host
    name              = module.database.database.name
    port              = module.database.database.port
    master_secret_arn = module.database.database.master_secret_arn
    secret_arns       = module.database.database.secret_arns
  }
  client_security_group_ids = {
    for name in local.application_components : name => module.database.client_security_group_ids[name]
  }
  runtime_roles = {
    for name in local.application_components : name => {
      id   = module.database.runtime_roles[name].id
      name = module.database.runtime_roles[name].name
    }
  }
  instance_profiles = module.database.instance_profiles
  api_repository = {
    arn            = aws_ecr_repository.application["api"].arn
    repository_url = aws_ecr_repository.application["api"].repository_url
  }
  queue_arn = aws_sqs_queue.confirmations.arn
}

# Route DNS through CloudFront to private S3 assets and the application's ALB origin.
module "frontend" {
  source              = "../modules/frontend"
  name_prefix         = var.name_prefix
  aws_account_id      = var.aws_account_id
  frontend            = var.frontend
  origin_verify_token = var.origin_verify_token
  alb_origin          = module.application.alb_origin
}

# Consume confirmations from SQS with only the consumer's database identity.
module "confirmations" {
  source                     = "../modules/confirmations"
  name_prefix                = var.name_prefix
  aws_account_id             = var.aws_account_id
  aws_region                 = var.aws_region
  confirmation_worker        = var.confirmation_worker
  application_subnet_ids     = module.network.network.application_subnet_ids
  consumer_security_group_id = module.database.client_security_group_ids["consumer"]
  consumer_role              = module.database.runtime_roles["consumer"]
  database = {
    host       = module.database.database.host
    name       = module.database.database.name
    port       = module.database.database.port
    secret_arn = module.database.database.secret_arns["consumer"]
  }
  lambda_repository = {
    name           = aws_ecr_repository.application["lambda"].name
    arn            = aws_ecr_repository.application["lambda"].arn
    repository_url = aws_ecr_repository.application["lambda"].repository_url
  }
  queue_arn                        = aws_sqs_queue.confirmations.arn
  queue_visibility_timeout_seconds = aws_sqs_queue.confirmations.visibility_timeout_seconds
}
