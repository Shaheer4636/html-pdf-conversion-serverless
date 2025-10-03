terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5.1"
    }
  }
}

provider "aws" {
  region = var.region
}

# ---- Unique name handling (prefix + optional random suffix)
resource "random_id" "suffix" {
  count       = var.add_random_suffix ? 1 : 0
  byte_length = 2
}

locals {
  base_prefix = "${var.name_prefix}-dev"
  prefix      = var.add_random_suffix ? "${local.base_prefix}-${random_id.suffix[0].hex}" : local.base_prefix
}

# =============================================================================
# Synthetics canary IAM role + policy (permissions kept; no canary created)
# =============================================================================
data "aws_iam_policy_document" "synthetics_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = [
        "synthetics.amazonaws.com",
        "lambda.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role" "synthetics" {
  name               = "${local.prefix}-synthetics-role"
  assume_role_policy = data.aws_iam_policy_document.synthetics_assume.json
  description        = "Role for CloudWatch Synthetics canaries (dev)"
}

data "aws_iam_policy_document" "synthetics_perm" {
  statement {
    sid       = "S3All"
    actions   = ["s3:*"]
    resources = ["*"]
  }
  statement {
    sid       = "LogsAll"
    actions   = ["logs:*"]
    resources = ["*"]
  }
  statement {
    sid       = "CWAll"
    actions   = ["cloudwatch:*"]
    resources = ["*"]
  }
  statement {
    sid       = "XRayAll"
    actions   = ["xray:*"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "synthetics_policy" {
  name        = "${local.prefix}-synthetics-policy"
  description = "Wide permissions for Synthetics canaries (dev)"
  policy      = data.aws_iam_policy_document.synthetics_perm.json
}

resource "aws_iam_role_policy_attachment" "synthetics_attach" {
  role       = aws_iam_role.synthetics.name
  policy_arn = aws_iam_policy.synthetics_policy.arn
}

# =============================================================================
# Uptime Lambda role + policy
# =============================================================================
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.prefix}-uptime-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  description        = "Role for uptime/reporting Lambda (dev)"
}

data "aws_iam_policy_document" "lambda_perm" {
  statement {
    sid       = "S3All"
    actions   = ["s3:*"]
    resources = ["*"]
  }
  statement {
    sid       = "LogsAll"
    actions   = ["logs:*"]
    resources = ["*"]
  }
  statement {
    sid       = "CWAll"
    actions   = ["cloudwatch:*"]
    resources = ["*"]
  }
  statement {
    sid       = "QSAll"
    actions   = ["quicksight:*"]
    resources = ["*"]
  }
  statement {
    sid       = "XRayAll"
    actions   = ["xray:*"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "lambda_policy" {
  name        = "${local.prefix}-uptime-lambda-policy"
  description = "Wide permissions for uptime/reporting Lambda (dev)"
  policy      = data.aws_iam_policy_document.lambda_perm.json
}

resource "aws_iam_role_policy_attachment" "lambda_attach" {
  role       = aws_iam_role.lambda.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

# =============================================================================
# EventBridge Scheduler role (invoke Lambda)
# =============================================================================
resource "aws_iam_role" "scheduler" {
  name = "${local.prefix}-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "scheduler.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
  description = "Role for EventBridge Scheduler to invoke Lambda (dev)"
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name = "${local.prefix}-scheduler-invoke"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = ["lambda:InvokeFunction"],
      Resource = "*"
    }]
  })
}

# =============================================================================
# Outputs (no canary outputs)
# =============================================================================
output "synthetics_role_arn" { value = aws_iam_role.synthetics.arn }
output "synthetics_policy_arn" { value = aws_iam_policy.synthetics_policy.arn }
output "lambda_role_arn"      { value = aws_iam_role.lambda.arn }
output "lambda_policy_arn"    { value = aws_iam_policy.lambda_policy.arn }
output "scheduler_role_arn"   { value = aws_iam_role.scheduler.arn }
