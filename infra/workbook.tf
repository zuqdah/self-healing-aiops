# The dashboard. Every tile reads the JSON incident records the responder
# writes to stdout, which Container Apps ships to Log Analytics. The queries
# are built here rather than in a JSON file so the KQL stays readable.

locals {
  # Each incident is logged several times as it progresses; the last record
  # for an id is its final state.
  incident_base = <<-KQL
    ContainerAppConsoleLogs_CL
    | where ContainerAppName_s == "${module.responder.name}"
    | extend record = parse_json(Log_s)
    | where tostring(record.event) == "incident"
    | summarize arg_max(TimeGenerated, *) by incident_id = tostring(record.id)
  KQL

  workbook_items = [
    {
      type = 1
      content = {
        json = <<-MD
          ## Self-healing AIOps

          Every incident below was detected by an alert, diagnosed by an agent reading logs, and decided by policy. `auto` ran unattended; `escalate` waited for a person; `refuse` was never eligible.
        MD
      }
      name = "header"
    },
    {
      type = 3
      content = {
        version       = "KqlItem/1.0"
        title         = "Incidents"
        query         = <<-KQL
          ${local.incident_base}
          | project TimeGenerated,
                    incident_id,
                    status = tostring(record.status),
                    decision = tostring(record.decision),
                    action = tostring(record.proposed_action),
                    target = tostring(record.proposed_target),
                    confidence = tostring(record.confidence),
                    mttr_seconds = todouble(record.mttr_seconds),
                    cost_usd = todouble(record.cost_usd),
                    diagnosis = tostring(record.diagnosis)
          | order by TimeGenerated desc
        KQL
        size          = 0
        queryType     = 0
        resourceType  = "microsoft.operationalinsights/workspaces"
        visualization = "table"
      }
      name = "incidents"
    },
    {
      type = 3
      content = {
        version       = "KqlItem/1.0"
        title         = "Mean time to recovery"
        query         = <<-KQL
          ${local.incident_base}
          | where isnotempty(record.mttr_seconds)
          | summarize MTTR_seconds = avg(todouble(record.mttr_seconds)),
                      Fastest = min(todouble(record.mttr_seconds)),
                      Slowest = max(todouble(record.mttr_seconds)),
                      Incidents = count()
        KQL
        size          = 4
        queryType     = 0
        resourceType  = "microsoft.operationalinsights/workspaces"
        visualization = "table"
      }
      name = "mttr"
    },
    {
      type = 3
      content = {
        version       = "KqlItem/1.0"
        title         = "Autonomy and cost"
        query         = <<-KQL
          ${local.incident_base}
          | summarize Incidents = count(),
                      Resolved_unattended = countif(tostring(record.decision) == "auto" and tostring(record.status) == "resolved"),
                      Escalated = countif(tostring(record.status) == "awaiting_approval"),
                      Refused = countif(tostring(record.status) == "refused"),
                      Diagnosis_cost_usd = round(sum(todouble(record.cost_usd)), 4),
                      Tokens = sum(toint(record.prompt_tokens) + toint(record.completion_tokens))
          | extend Unattended_rate = strcat(round(100.0 * Resolved_unattended / Incidents, 1), "%")
        KQL
        size          = 4
        queryType     = 0
        resourceType  = "microsoft.operationalinsights/workspaces"
        visualization = "table"
      }
      name = "autonomy"
    },
  ]
}

resource "azurerm_application_insights_workbook" "incidents" {
  # Workbook names must be a GUID; a stable one keeps redeploys in place.
  name                = "7c3f7b64-0a2f-4d63-9a3a-9b6a5c2f1d40"
  resource_group_name = data.azurerm_resource_group.lab.name
  location            = local.location
  display_name        = "Self-healing AIOps: incidents, MTTR, and cost"
  source_id           = lower(module.observability.log_analytics_workspace_id)

  data_json = jsonencode({
    version   = "Notebook/1.0"
    items     = local.workbook_items
    "$schema" = "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json"
  })

  tags = local.tags
}
