variable "name" {
  description = "Name suffix for the alert rule and action group."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to deploy into."
  type        = string
}

variable "workspace_id" {
  description = "Log Analytics workspace the alert query runs against."
  type        = string
}

variable "workload_app_name" {
  description = "Container app whose logs are watched."
  type        = string
}

variable "responder_alert_url" {
  description = "Responder webhook URL, including its path token."
  type        = string
  sensitive   = true
}

variable "failure_threshold" {
  description = "Failed requests within the window that constitute an incident."
  type        = number
  default     = 3
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
