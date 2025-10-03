variable "region" {
  description = "AWS region for the buckets"
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Project prefix added to both buckets (human readable)"
  type        = string
  default     = "uptime"
}

variable "add_random_suffix" {
  description = "Append a short random suffix for global uniqueness"
  type        = bool
  default     = true
}

variable "canary_bucket_name" {
  description = "Base name for the Synthetics canary artifact bucket (letters, numbers, hyphens). Do not include the prefix; we'll add it."
  type        = string
}

variable "report_bucket_name" {
  description = "Base name for the PDF report output bucket (letters, numbers, hyphens). Do not include the prefix; we'll add it."
  type        = string
}

variable "force_destroy" {
  description = "If true, allows Terraform to destroy non-empty buckets (use carefully in dev)"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Optional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
