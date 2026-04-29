resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

locals {
  name        = "${var.project}-${var.environment}"
  unique_name = "${var.project}${var.environment}${random_string.suffix.result}"

  common_tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.common_tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.common_tags
}

resource "azurerm_container_registry" "main" {
  name                = replace("acr${local.unique_name}", "-", "")
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.common_tags
}

resource "azurerm_user_assigned_identity" "container_apps" {
  name                = "id-${local.name}-apps"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

resource "azurerm_role_assignment" "container_apps_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.container_apps.principal_id
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                   = "psql-${local.name}-${random_string.suffix.result}"
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = "16"
  administrator_login    = var.postgres_admin_user
  administrator_password = var.postgres_admin_password
  storage_mb             = 32768
  sku_name               = "B_Standard_B1ms"
  backup_retention_days  = 7
  tags                   = local.common_tags
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  count            = var.allow_azure_services_to_postgres ? 1 : 0
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.project
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

resource "azurerm_key_vault" "main" {
  name                       = substr(replace("kv-${local.unique_name}", "-", ""), 0, 24)
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  tags                       = local.common_tags
}

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault_access_policy" "deployer" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = [
    "Get",
    "List",
    "Set",
    "Delete",
    "Recover",
    "Purge",
  ]
}

# Allow Container Apps' managed identity to read secrets from Key Vault.
# This lets the Container Apps pull secrets directly from Key Vault rather
# than having the values duplicated in the Container App secret blocks.
resource "azurerm_key_vault_access_policy" "container_apps" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.container_apps.principal_id

  secret_permissions = ["Get"]

  depends_on = [azurerm_key_vault_access_policy.deployer]
}

resource "azurerm_key_vault_secret" "fernet_key" {
  name         = "fernet-key"
  value        = var.fernet_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.deployer]
}

resource "azurerm_key_vault_secret" "postgres_password" {
  name         = "postgres-admin-password"
  value        = var.postgres_admin_password
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.deployer]
}

resource "azurerm_key_vault_secret" "smtp_password" {
  name         = "smtp-password"
  value        = var.smtp_password
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.deployer]
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.name}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.common_tags
}

locals {
  app_env = [
    { name = "OPS_DB_USER", value = var.postgres_admin_user },
    { name = "OPS_DB_NAME", value = azurerm_postgresql_flexible_server_database.app.name },
    { name = "OPS_DB_HOST", value = azurerm_postgresql_flexible_server.main.fqdn },
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
}

resource "azurerm_container_app" "caller" {
  name                         = "ca-${local.name}-caller"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.common_tags
  depends_on                   = [azurerm_role_assignment.container_apps_acr_pull, azurerm_key_vault_access_policy.container_apps]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.container_apps.id]
  }

  ingress {
    external_enabled = true
    target_port      = 8001

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  secret {
    name                = "ops-db-pass"
    key_vault_secret_id = azurerm_key_vault_secret.postgres_password.id
    identity            = azurerm_user_assigned_identity.container_apps.id
  }

  secret {
    name                = "fernet-key"
    key_vault_secret_id = azurerm_key_vault_secret.fernet_key.id
    identity            = azurerm_user_assigned_identity.container_apps.id
  }

  secret {
    name                = "smtp-pass"
    key_vault_secret_id = azurerm_key_vault_secret.smtp_password.id
    identity            = azurerm_user_assigned_identity.container_apps.id
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.container_apps.id
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name   = "caller"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "APP_MODULE"
        value = "app.phonebanking.main:app"
      }

      env {
        name  = "PORT"
        value = "8001"
      }

      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      env {
        name        = "OPS_DB_PASS"
        secret_name = "ops-db-pass"
      }

      env {
        name        = "FERNET_KEY"
        secret_name = "fernet-key"
      }

      env {
        name        = "SMTP_PASS"
        secret_name = "smtp-pass"
      }
    }
  }
}

resource "azurerm_container_app" "admin" {
  name                         = "ca-${local.name}-admin"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.common_tags
  depends_on                   = [azurerm_role_assignment.container_apps_acr_pull, azurerm_key_vault_access_policy.container_apps]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.container_apps.id]
  }

  ingress {
    external_enabled = true
    target_port      = 8002

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  secret {
    name                = "ops-db-pass"
    key_vault_secret_id = azurerm_key_vault_secret.postgres_password.id
    identity            = azurerm_user_assigned_identity.container_apps.id
  }

  secret {
    name                = "fernet-key"
    key_vault_secret_id = azurerm_key_vault_secret.fernet_key.id
    identity            = azurerm_user_assigned_identity.container_apps.id
  }

  secret {
    name                = "smtp-pass"
    key_vault_secret_id = azurerm_key_vault_secret.smtp_password.id
    identity            = azurerm_user_assigned_identity.container_apps.id
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.container_apps.id
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "admin"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "APP_MODULE"
        value = "app.admin.main:app"
      }

      env {
        name  = "PORT"
        value = "8002"
      }

      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      env {
        name        = "OPS_DB_PASS"
        secret_name = "ops-db-pass"
      }

      env {
        name        = "FERNET_KEY"
        secret_name = "fernet-key"
      }

      env {
        name        = "SMTP_PASS"
        secret_name = "smtp-pass"
      }
    }
  }
}
