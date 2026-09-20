data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "lab" {
  name = var.resource_group_name
}

resource "random_string" "suffix" {
  length  = 5
  lower   = true
  upper   = false
  numeric = true
  special = false
}

# Secrets generated here, stored in Key Vault, never printed to a log.
resource "random_password" "tool_key" {
  length  = 48
  special = false
}

resource "random_password" "responder_key" {
  length  = 48
  special = false
}

resource "random_password" "alert_token" {
  length  = 48
  special = false
}

locals {
  name     = "aiops-${random_string.suffix.result}"
  location = coalesce(var.location, data.azurerm_resource_group.lab.location)

  tags = merge(var.tags, {
    workload   = "self-healing-aiops"
    managed-by = "terraform"
    repo       = "github.com/zuqdah/self-healing-aiops"
  })

  demo_app_name = "ca-${local.name}-demo"
}

# ---------------------------------------------------------------------------
# Shared building blocks, reused from earlier labs at pinned commits
# ---------------------------------------------------------------------------

module "observability" {
  # cf3c8dc is tag v1.1.0 of the landing zone lab.
  source = "git::https://github.com/zuqdah/azure-agent-landing-zone.git//modules/observability?ref=cf3c8dc50ab7eebf4ace424e40f19077081fd618"

  name                = local.name
  location            = local.location
  resource_group_name = data.azurerm_resource_group.lab.name
  daily_quota_gb      = var.log_daily_quota_gb
  tags                = local.tags
}

module "keyvault" {
  # 335bc3b is tag v1.0.0 of the landing zone lab.
  source = "git::https://github.com/zuqdah/azure-agent-landing-zone.git//modules/keyvault?ref=335bc3bb3b64b633c028b6df8d21599a294e8f6c"

  name                = replace(local.name, "-", "")
  location            = local.location
  resource_group_name = data.azurerm_resource_group.lab.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  tags                = local.tags
}

module "foundry" {
  # 74bb82f is tag v1.0.0 of the agentic ops copilot lab.
  source = "git::https://github.com/zuqdah/agentic-ops-copilot.git//modules/foundry?ref=74bb82faa1171002b96df0fe297d91551fc4af7d"

  name                 = local.name
  location             = local.location
  resource_group_name  = data.azurerm_resource_group.lab.name
  project_display_name = "Self-healing AIOps"
  project_description  = "Diagnoses incidents from logs so the responder can decide what to do."
  model_name           = var.model_name
  model_version        = var.model_version
  deployment_sku       = var.model_deployment_sku
  capacity_ktpm        = var.model_capacity_ktpm
  tags                 = local.tags
}

# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------

# The tool server: reads the estate so the agent can investigate.
resource "azurerm_user_assigned_identity" "tools" {
  name                = "id-${local.name}-tools"
  location            = local.location
  resource_group_name = data.azurerm_resource_group.lab.name
  tags                = local.tags
}

# The responder: performs the one remediation, and calls the agent.
resource "azurerm_user_assigned_identity" "responder" {
  name                = "id-${local.name}-responder"
  location            = local.location
  resource_group_name = data.azurerm_resource_group.lab.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "tools_reader" {
  scope                = data.azurerm_resource_group.lab.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.tools.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "tools_logs" {
  scope                = module.observability.log_analytics_workspace_id
  role_definition_name = "Log Analytics Reader"
  principal_id         = azurerm_user_assigned_identity.tools.principal_id
  principal_type       = "ServicePrincipal"
}

# The responder can restart a revision and nothing else. Even a compromised
# responder cannot change an app, its image, or its secrets.
resource "azurerm_role_assignment" "responder_restart" {
  scope              = data.azurerm_resource_group.lab.id
  role_definition_id = var.restart_role_definition_id
  principal_id       = azurerm_user_assigned_identity.responder.principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "responder_foundry" {
  scope                = module.foundry.account_id
  role_definition_name = "Foundry User"
  principal_id         = azurerm_user_assigned_identity.responder.principal_id
  principal_type       = "ServicePrincipal"
}

# The pipeline publishes the agent definition, which is a data-plane action.
resource "azurerm_role_assignment" "deployer_foundry" {
  scope                = module.foundry.account_id
  role_definition_name = "Foundry Project Manager"
  principal_id         = data.azurerm_client_config.current.object_id
}

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

resource "azurerm_role_assignment" "deployer_kv_secrets_officer" {
  scope                = module.keyvault.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "tools_kv" {
  scope                = module.keyvault.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.tools.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "responder_kv" {
  scope                = module.keyvault.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.responder.principal_id
  principal_type       = "ServicePrincipal"
}

resource "time_sleep" "rbac_propagation" {
  create_duration = "60s"

  depends_on = [
    azurerm_role_assignment.deployer_kv_secrets_officer,
    azurerm_role_assignment.tools_kv,
    azurerm_role_assignment.responder_kv,
  ]
}

resource "time_offset" "secret_expiry" {
  offset_days = 30
}

resource "azurerm_key_vault_secret" "tool_key" {
  name            = "tool-server-key"
  value           = random_password.tool_key.result
  key_vault_id    = module.keyvault.id
  content_type    = "Shared key Foundry presents to the tool server"
  expiration_date = time_offset.secret_expiry.rfc3339

  depends_on = [time_sleep.rbac_propagation]
}

resource "azurerm_key_vault_secret" "responder_key" {
  name            = "responder-key"
  value           = random_password.responder_key.result
  key_vault_id    = module.keyvault.id
  content_type    = "Shared key for approving escalated incidents"
  expiration_date = time_offset.secret_expiry.rfc3339

  depends_on = [time_sleep.rbac_propagation]
}

resource "azurerm_key_vault_secret" "alert_token" {
  name            = "alert-token"
  value           = random_password.alert_token.result
  key_vault_id    = module.keyvault.id
  content_type    = "Path token Azure Monitor uses to call the responder"
  expiration_date = time_offset.secret_expiry.rfc3339

  depends_on = [time_sleep.rbac_propagation]
}

# ---------------------------------------------------------------------------
# Workloads
# ---------------------------------------------------------------------------

resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${local.name}"
  location                   = local.location
  resource_group_name        = data.azurerm_resource_group.lab.name
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = module.observability.log_analytics_workspace_id
  tags                       = local.tags
}

# The agent's tools, reusing the image published by the previous lab.
module "tool_server" {
  source = "../modules/container-app"

  name                       = "${local.name}-tools"
  container_name             = "tools"
  resource_group_name        = data.azurerm_resource_group.lab.name
  environment_id             = azurerm_container_app_environment.this.id
  environment_default_domain = azurerm_container_app_environment.this.default_domain
  identity_id                = azurerm_user_assigned_identity.tools.id
  image                      = var.tool_server_image
  secrets                    = { "lab-key" = azurerm_key_vault_secret.tool_key.versionless_id }
  secret_env                 = { LAB_KEY = "lab-key" }
  tags                       = local.tags

  env = {
    AZURE_SUBSCRIPTION_ID      = data.azurerm_client_config.current.subscription_id
    LAB_RESOURCE_GROUP         = data.azurerm_resource_group.lab.name
    LOG_ANALYTICS_WORKSPACE_ID = module.observability.log_analytics_workspace_customer_id
    AZURE_CLIENT_ID            = azurerm_user_assigned_identity.tools.client_id
  }
}

# The workload that breaks.
module "demo" {
  source = "../modules/container-app"

  name                       = "${local.name}-demo"
  container_name             = "demo"
  resource_group_name        = data.azurerm_resource_group.lab.name
  environment_id             = azurerm_container_app_environment.this.id
  environment_default_domain = azurerm_container_app_environment.this.default_domain
  identity_id                = azurerm_user_assigned_identity.tools.id
  image                      = var.demo_image
  tags                       = local.tags

  # Kept warm so an injected fault survives to be alerted on rather than
  # disappearing when the app scales to zero.
  min_replicas = 1

  env = {
    SERVICE_NAME = "demo-workload"
  }
}

# The responder.
module "responder" {
  source = "../modules/container-app"

  name                       = "${local.name}-responder"
  container_name             = "responder"
  resource_group_name        = data.azurerm_resource_group.lab.name
  environment_id             = azurerm_container_app_environment.this.id
  environment_default_domain = azurerm_container_app_environment.this.default_domain
  identity_id                = azurerm_user_assigned_identity.responder.id
  image                      = var.responder_image
  tags                       = local.tags

  # Incidents are held in memory, so the responder stays up.
  min_replicas = 1

  secrets = {
    "lab-key"     = azurerm_key_vault_secret.responder_key.versionless_id
    "alert-token" = azurerm_key_vault_secret.alert_token.versionless_id
  }

  secret_env = {
    LAB_KEY     = "lab-key"
    ALERT_TOKEN = "alert-token"
  }

  env = {
    AZURE_SUBSCRIPTION_ID   = data.azurerm_client_config.current.subscription_id
    LAB_RESOURCE_GROUP      = data.azurerm_resource_group.lab.name
    AZURE_CLIENT_ID         = azurerm_user_assigned_identity.responder.client_id
    PROJECT_ENDPOINT        = module.foundry.project_endpoint
    AGENT_NAME              = var.agent_name
    MANAGED_APPS            = local.demo_app_name
    DEFAULT_TARGET          = local.demo_app_name
    WORKLOAD_URL            = module.demo.url
    DAILY_REMEDIATION_LIMIT = tostring(var.daily_remediation_limit)
    INPUT_USD_PER_MTOK      = var.input_usd_per_mtok
    OUTPUT_USD_PER_MTOK     = var.output_usd_per_mtok
  }
}

# How Foundry authenticates to the tool server.
resource "azurerm_cognitive_account_connection_custom_keys" "tool_server" {
  name                 = var.mcp_connection_name
  cognitive_account_id = module.foundry.account_id
  category             = "CustomKeys"
  target               = "${module.tool_server.url}/mcp"

  custom_keys = {
    "x-lab-key" = random_password.tool_key.result
  }
}

# ---------------------------------------------------------------------------
# Detection and reporting
# ---------------------------------------------------------------------------

module "alert" {
  source = "../modules/incident-alert"

  name                = local.name
  location            = local.location
  resource_group_name = data.azurerm_resource_group.lab.name
  workspace_id        = module.observability.log_analytics_workspace_id
  workload_app_name   = module.demo.name
  responder_alert_url = "${module.responder.url}/alert/${random_password.alert_token.result}"
  failure_threshold   = var.failure_threshold
  tags                = local.tags
}

# The dashboard lives in workbook.tf.
