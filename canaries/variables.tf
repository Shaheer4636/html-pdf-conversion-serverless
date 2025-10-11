variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "canary_name" {
  description = "Name of the Synthetics canary"
  type        = string
}

variable "target_url" {
  description = "Endpoint the canary will hit each minute"
  type        = string
}

variable "artifacts_bucket_name" {
  description = "Existing S3 bucket where Synthetics artifacts are stored"
  type        = string
}

variable "synthetics_role_name" {
  description = "IAM role name for the canary execution"
  type        = string
}

variable "runtime_version" {
  description = "Synthetics runtime version"
  type        = string
  default     = "syn-nodejs-puppeteer-6.2"
}

variable "start_canary" {
  description = "Start the canary after create/update"
  type        = bool
  default     = true
}

variable "timeout_seconds" {
  description = "Per-run timeout"
  type        = number
  default     = 60
}

variable "success_retention_days" {
  description = "Retention days for successful runs"
  type        = number
  default     = 31
}

variable "failure_retention_days" {
  description = "Retention days for failed runs"
  type        = number
  default     = 31
}
