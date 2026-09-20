# What turns a failing workload into an incident: a log query that notices
# errors, and an action group that calls the responder.

resource "azurerm_monitor_action_group" "responder" {
  name                = "ag-${var.name}-responder"
  resource_group_name = var.resource_group_name
  short_name          = "aiops"

  webhook_receiver {
    name = "responder"
    # The shared secret is in the path: Azure Monitor's plain webhooks
    # cannot send custom headers. A production deployment would use a
    # secure webhook with an Entra identity instead.
    service_uri = var.responder_alert_url
    # Common Alert Schema gives the responder a stable payload shape.
    use_common_alert_schema = true
  }

  tags = var.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "errors" {
  name                = "alert-${var.name}-errors"
  location            = var.location
  resource_group_name = var.resource_group_name
  scopes              = [var.workspace_id]
  severity            = 2

  # The workload logs one JSON line per failed request. A handful in five
  # minutes is a real fault, not a blip.
  evaluation_frequency = "PT5M"
  window_duration      = "PT5M"

  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where ContainerAppName_s == "${var.workload_app_name}"
      | where Log_s has "request_failed"
      | summarize Failures = count()
    KQL
    time_aggregation_method = "Count"
    threshold               = var.failure_threshold
    operator                = "GreaterThanOrEqual"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  auto_mitigation_enabled = true
  description             = "The demo workload is returning errors; the responder investigates and decides what to do."

  action {
    action_groups = [azurerm_monitor_action_group.responder.id]
  }

  tags = var.tags
}
