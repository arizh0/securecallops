output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "container_registry_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "caller_url" {
  value = "https://${azurerm_container_app.caller.latest_revision_fqdn}"
}

output "admin_url" {
  value = "https://${azurerm_container_app.admin.latest_revision_fqdn}"
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}
