# Vault auto-hébergé (stockage Raft, un seul nœud). Écoute uniquement dans le réseau Docker :
# l'hôte n'y accède que via 127.0.0.1:8200 (tunnel SSH pour l'UI). TLS non requis : trafic interne.
ui            = true
disable_mlock = false
api_addr      = "http://vault:8200"
cluster_addr  = "http://vault:8201"

storage "raft" {
  path    = "/vault/file"
  node_id = "lexbenin-vault-1"
}

listener "tcp" {
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_disable     = true
}
