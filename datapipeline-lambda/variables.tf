variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Base name for Lambda (human readable)"
  type        = string
  default     = "uptime"
}

variable "add_random_suffix" {
  description = "Append a short random suffix to the function name"
  type        = bool
  default     = true
}

variable "lambda_role_arn" {
  description = "IAM role ARN for the Lambda (from IAM stack output)"
  type        = string
}

variable "artifact_bucket" {
  description = "S3 bucket name for Synthetics artifacts (from S3 stack output)"
  type        = string
}

variable "reports_bucket" {
  description = "S3 bucket name for report outputs (from S3 stack output)"
  type        = string
}

variable "artifact_prefix" {
  description = "Prefix inside the artifact bucket; if empty defaults to canary/<region>/<name_prefix>"
  type        = string
  default     = ""
}

variable "reports_prefix" {
  description = "Prefix inside the reports bucket"
  type        = string
  default     = "uptime"
}

# Optional presentation / behavior
variable "company"       { type = string, default = "Situs-AMC" }
variable "service"       { type = string, default = "Useful App" }
variable "client"        { type = string, default = "CitiBank" }
variable "only_browser"  { type = string, default = "ANY" }
variable "fail_streak"   { type = number, default = 3 }
variable "treat_missing" { type = bool,   default = false }
variable "slo_target"    { type = string, default = "auto" }

# The Python source file path (relative to this folder)
variable "source_py" {
  description = "Path to lambda_generate_uptime.py"
  type        = string
  default     = "lambda_generate_uptime.py"
}
