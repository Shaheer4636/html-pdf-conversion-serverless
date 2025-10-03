terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws     = { source = "hashicorp/aws",     version = ">= 5.40.0" }
    random  = { source = "hashicorp/random",  version = ">= 3.5.1" }
    archive = { source = "hashicorp/archive", version = ">= 2.4.0" }
  }
}

provider "aws" {
  region = var.region
}

# Optional random suffix for the function name
resource "random_id" "suffix" {
  count       = var.add_random_suffix ? 1 : 0
  byte_length = 2
}

locals {
  fn_name = lower(
    var.add_random_suffix
      ? "${var.name_prefix}-uplambda-${random_id.suffix[0].hex}"
      : "${var.name_prefix}-uplambda"
  )

  art_prefix = var.artifact_prefix != "" ? var.artifact_prefix : "canary/${var.region}/${var.name_prefix}"
}

# Package the Python file as lambda_function.py
data "archive_file" "zip" {
  type        = "zip"
  output_path = "${path.module}/lambda.zip"

  source {
    filename = "lambda_function.py"
    content  = file(var.source_py)
  }
}

resource "aws_lambda_function" "uptime" {
  function_name    = local.fn_name
  role             = var.lambda_role_arn
  handler          = "lambda_function.handler"
  runtime          = "python3.11"
  filename         = data.archive_file.zip.output_path
  source_code_hash = data.archive_file.zip.output_base64sha256
  memory_size      = 1024
  timeout          = 900
  architectures    = ["x86_64"]

  environment {
    variables = {
      ART_BUCKET     = var.artifact_bucket
      ART_PREFIX     = local.art_prefix
      REPORTS_BUCKET = var.reports_bucket
      REPORTS_PREFIX = var.reports_prefix

      COMPANY        = var.company
      SERVICE        = var.service
      CLIENT         = var.client

      ONLY_BROWSER   = var.only_browser
      FAIL_STREAK    = tostring(var.fail_streak)
      TREAT_MISSING  = tostring(var.treat_missing)
      SLO_TARGET     = var.slo_target
    }
  }

  tags = {
    Project = var.name_prefix
    Region  = var.region
  }
}

output "lambda_function_name" { value = aws_lambda_function.uptime.function_name }
output "lambda_function_arn"  { value = aws_lambda_function.uptime.arn }
