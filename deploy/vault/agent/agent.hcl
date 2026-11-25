# Vault Agent : s'authentifie par AppRole et rend /vault/secrets/backend.env
# (relu par le backend via Settings.env_file). Re-rendu automatique si un secret change.
pid_file = "/tmp/vault-agent.pid"

vault {
  address = "http://vault:8200"
  retry {
    num_retries = -1
  }
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path                   = "/vault/approle/role_id"
      secret_id_file_path                 = "/vault/approle/secret_id"
      remove_secret_id_file_after_reading = false
    }
  }
  sink "file" {
    config = {
      path = "/tmp/agent-token"
    }
  }
}

template {
  source      = "/vault/agent/backend.env.ctmpl"
  destination = "/vault/secrets/backend.env"
  perms       = "0644"
  error_on_missing_key = true
}
