output "demo_url" {
  description = "The workload that can be broken: POST /break to stage an incident."
  value       = module.demo.url
}

output "responder_url" {
  description = "The incident responder. GET /incidents to see what happened."
  value       = module.responder.url
}

output "tool_server_url" {
  description = "MCP tool server the agent investigates with."
  value       = module.tool_server.url
}

output "project_endpoint" {
  description = "Foundry project endpoint used to publish the agent."
  value       = module.foundry.project_endpoint
}

output "deployment_name" {
  description = "Model deployment the agent uses."
  value       = module.foundry.deployment_name
}

output "mcp_endpoint" {
  description = "MCP endpoint registered with the agent."
  value       = "${module.tool_server.url}/mcp"
}

output "mcp_connection_name" {
  description = "Project connection the agent references for tool server auth."
  value       = azurerm_cognitive_account_connection_custom_keys.tool_server.name
}

output "demo_app_name" {
  description = "Container app name of the demo workload."
  value       = module.demo.name
}

output "workbook_url" {
  description = "Azure portal link to the incidents, MTTR, and cost dashboard."
  value       = "https://portal.azure.com/#@/resource${azurerm_application_insights_workbook.incidents.id}"
}

output "key_vault_name" {
  description = "Key Vault holding the lab's shared keys."
  value       = module.keyvault.name
}

output "workspace_guid" {
  description = "Log Analytics workspace GUID, for querying via the data-plane API."
  value       = module.observability.log_analytics_workspace_customer_id
}
