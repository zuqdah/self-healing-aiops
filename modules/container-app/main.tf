locals {
  # The MCP transport and the alert webhook both need the app's hostname
  # before the app exists; the environment's domain is known first.
  fqdn = "ca-${var.name}.${var.environment_default_domain}"
}

resource "azurerm_container_app" "this" {
  name                         = "ca-${var.name}"
  container_app_environment_id = var.environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  # Resolved from Key Vault at runtime by the app's own identity.
  dynamic "secret" {
    for_each = var.secrets
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = var.identity_id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = var.container_name
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      dynamic "env" {
        for_each = merge(var.env, { PUBLIC_HOSTNAME = local.fqdn })
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/healthz"
        port      = 8000
      }

      readiness_probe {
        transport = "HTTP"
        path      = "/healthz"
        port      = 8000
      }
    }

    http_scale_rule {
      name                = "http"
      concurrent_requests = "20"
    }
  }

  tags = var.tags
}
