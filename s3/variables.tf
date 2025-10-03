variable "region"            { type = string, default = "us-east-1" }
variable "name_prefix"       { type = string, default = "uptime" }
variable "add_random_suffix" { type = bool,   default = true }
variable "canary_bucket_name" { type = string }
variable "report_bucket_name" { type = string }
variable "force_destroy"     { type = bool,   default = false }
variable "tags"              { type = map(string), default = {} }
