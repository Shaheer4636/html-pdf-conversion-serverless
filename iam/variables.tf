# ---- Provider inputs ----
variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

# ---- Naming controls (used across IAM and Canary) ----
variable "name_prefix" {
  description = "Base name; '-dev' (and optionally a random suffix) is appended to every IAM resource"
  type        = string
  default     = "uptime"
}

variable "add_random_suffix" {
  description = "Append a short random suffix to avoid name collisions"
  type        = bool
  default     = true
}

# ---- Canary-specific ----
variable "canary_name" {
  description = "Explicit canary name. If omitted, use the same prefix (lowercase/alnum/hyphen)."
  type        = string
  default     = "clonerainthoscom"
}

variable "target_url" {
  description = "Endpoint URL the canary will GET"
  type        = string
}

variable "artifact_bucket" {
  description = "S3 bucket for canary run artifacts"
  type        = string
}

variable "artifact_prefix" {
  description = "S3 key prefix for artifacts (no trailing slash)"
  type        = string
  default     = "canary/${var.region}/clonerainthoscom"
}

variable "runtime_version" {
  description = "Synthetics runtime"
  type        = string
  default     = "syn-nodejs-puppeteer-8.0"
}

variable "schedule_expression" {
  description = "How often to run the canary"
  type        = string
  default     = "rate(1 minute)"
}

variable "timeout_seconds" {
  description = "Per-run timeout"
  type        = number
  default     = 60
}

variable "memory_mb" {
  description = "Lambda memory for the canary"
  type        = number
  default     = 960
}

variable "artifact_retention_days" {
  description = "Days to retain success/failure artifacts"
  type        = number
  default     = 31
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the canary Lambda log group"
  type        = number
  default     = 14
}

