output "alert_rule_id" {
  description = "Resource ID of the log search alert rule."
  value       = azurerm_monitor_scheduled_query_rules_alert_v2.errors.id
}

output "action_group_id" {
  description = "Resource ID of the action group that calls the responder."
  value       = azurerm_monitor_action_group.responder.id
}
