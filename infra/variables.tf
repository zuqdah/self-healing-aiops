variable "resource_group_name" {
  description = "Existing resource group created by bootstrap/."
  type        = string
  default     = "rg-aiops-lab"
}

variable "location" {
  description = "Region override. Defaults to the resource group's region."
  type        = string
  default     = null
}

variable "restart_role_definition_id" {
  description = "Role definition ID of the restart-only custom role created by bootstrap."
  type        = string
}

variable "tool_server_image" {
  description = "MCP tool server image. Reused from the agentic ops copilot lab."
  type        = string
  default     = "ghcr.io/zuqdah/agentops-mcp:latest"
}

variable "demo_image" {
  description = "Image for the demo workload that can be broken."
  type        = string
  default     = "ghcr.io/zuqdah/aiops-demo:latest"
}

variable "responder_image" {
  description = "Image for the incident responder."
  type        = string
  default     = "ghcr.io/zuqdah/aiops-responder:latest"
}

variable "agent_name" {
  description = "Name of the Foundry agent that diagnoses incidents."
  type        = string
  default     = "aiops-diagnostician"
}

variable "mcp_connection_name" {
  description = "Project connection holding the tool server's key."
  type        = string
  default     = "tool-server"
}

variable "daily_remediation_limit" {
  description = "Unattended remediations allowed per app per day before incidents escalate to a human."
  type        = number
  default     = 3
}

variable "failure_threshold" {
  description = "Failed requests in five minutes that constitute an incident."
  type        = number
  default     = 3
}

variable "model_name" {
  description = "Model to deploy."
  type        = string
  default     = "gpt-5.4-mini"
}

variable "model_version" {
  description = "Model version to deploy."
  type        = string
  default     = "2026-03-17"
}

variable "model_deployment_sku" {
  description = "Deployment type. Check `az cognitiveservices usage list` for quota before changing it."
  type        = string
  default     = "DataZoneStandard"
}

variable "model_capacity_ktpm" {
  description = "Deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 5
}

variable "input_usd_per_mtok" {
  description = "Input token price used to cost each diagnosis."
  type        = string
  default     = "0.825"
}

variable "output_usd_per_mtok" {
  description = "Output token price used to cost each diagnosis."
  type        = string
  default     = "4.95"
}

variable "log_daily_quota_gb" {
  description = "Daily Log Analytics ingestion cap in GB."
  type        = number
  default     = 0.1
}

variable "tags" {
  description = "Additional tags applied to every resource."
  type        = map(string)
  default     = {}
}
