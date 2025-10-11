region               = "us-east-1"

# Exact names you asked for
synthetics_role_name  = "uptime-dev-7ee3-synthetics-role"
artifacts_bucket_name = "citi-uat-1-10b4-synthetics-artifacts"

# Canary specifics
canary_name  = "rainthos-heartbeat-1m"
target_url   = "https://rainthos.com/"

# Optional (keep defaults or change)
runtime_version        = "syn-nodejs-puppeteer-6.2"
start_canary           = true
timeout_seconds        = 60
success_retention_days = 31
failure_retention_days = 31
