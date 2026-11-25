# Lecture seule des secrets applicatifs de production (backend + worker)
path "secret/data/lexbenin/prod/backend" {
  capabilities = ["read"]
}
path "secret/metadata/lexbenin/prod/backend" {
  capabilities = ["read"]
}
