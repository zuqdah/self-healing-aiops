variable "name" {
  description = "Name suffix; the app is named ca-<name>."
  type        = string
}

variable "container_name" {
  description = "Name of the container inside the app."
  type        = string
  default     = "app"
}

variable "resource_group_name" {
  description = "Resource group to deploy into."
  type        = string
}

variable "environment_id" {
  description = "Container Apps environment to run in."
  type        = string
}

variable "environment_default_domain" {
  description = "Default domain of that environment, used to derive the app's hostname."
  type        = string
}

variable "identity_id" {
  description = "Resource ID of the user-assigned identity the app runs as."
  type        = string
}

variable "image" {
  description = "Container image to run."
  type        = string
}

variable "env" {
  description = "Plain environment variables."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Container app secrets: secret name to versionless Key Vault secret ID."
  type        = map(string)
  default     = {}
}

variable "secret_env" {
  description = "Environment variables sourced from secrets: variable name to secret name."
  type        = map(string)
  default     = {}
}

variable "cpu" {
  description = "vCPU per replica."
  type        = number
  default     = 0.25
}

variable "memory" {
  description = "Memory per replica."
  type        = string
  default     = "0.5Gi"
}

variable "min_replicas" {
  description = "Minimum replicas. Zero means the app costs nothing while idle."
  type        = number
  default     = 0
}

variable "max_replicas" {
  description = "Maximum replicas."
  type        = number
  default     = 1
}

variable "tags" {
  description = "Tags applied to the app."
  type        = map(string)
  default     = {}
}
