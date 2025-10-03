region          = "us-east-1"
name_prefix     = "uptime"
add_random_suffix = true

# Canary
canary_name     = "citi-uat"
target_url      = "https://your.service.example.com/health"

# S3 for artifacts (must exist)
artifact_bucket = "canary-output-rainthos-009"
artifact_prefix = "canary/us-east-1/clonerainthoscom"

# Runtime + schedule
runtime_version     = "syn-nodejs-puppeteer-8.0"
schedule_expression = "rate(1 minute)"
timeout_seconds     = 60
memory_mb           = 960

# Retention
artifact_retention_days = 31
log_retention_days      = 14
