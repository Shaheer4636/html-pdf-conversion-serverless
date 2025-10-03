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
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
  }
}

# ---- Provider ----
provider "aws" {
  region = var.region
}

# ---- Unique name handling (prevents EntityAlreadyExists) ----
resource "random_id" "suffix" {
  count       = var.add_random_suffix ? 1 : 0
  byte_length = 2
}

locals {
  base_prefix = "${var.name_prefix}-dev"
  prefix      = var.add_random_suffix ? "${local.base_prefix}-${random_id.suffix[0].hex}" : local.base_prefix
}

# ====================================================================================
# Synthetics canary role + managed policy (wide dev permissions)
# ====================================================================================

data "aws_iam_policy_document" "synthetics_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type = "Service"
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

# ====================================================================================
# Uptime Lambda role + managed policy (wide dev permissions)
# ====================================================================================

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

# ====================================================================================
# EventBridge Scheduler role (inline policy: invoke any Lambda in dev)
# ====================================================================================

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

# ====================================================================================
# Canary: simple HTTP check with Chrome (Puppeteer), every minute
# ====================================================================================

# Package canary JS
data "archive_file" "canary_zip" {
  type        = "zip"
  output_path = "${path.module}/canary.zip"

  source {
    filename = "index.js"
    content  = <<-JS
      'use strict';
      const synthetics = require('Synthetics');
      const log = require('SyntheticsLogger');

      const canary = async function () {
        const url = process.env.TARGET_URL;
        if (!url) { throw new Error('TARGET_URL is not set'); }

        const page = await synthetics.getPage();

        // Navigate and wait for network to be mostly idle
        const resp = await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
        await synthetics.takeScreenshot('loaded', 'endpoint');

        const status = resp && resp.status ? resp.status() : 0;
        log.info('HTTP status: ' + status);
        if (status >= 400 || status === 0) {
          throw new Error('Endpoint returned bad status: ' + status);
        }

        // small delay to stabilize metrics
        await page.waitForTimeout(1000);
      };

      exports.handler = async () => {
        return await canary();
      };
    JS
  }
}

resource "aws_cloudwatch_log_group" "canary" {
  name              = "/aws/lambda/cwsyn-${var.canary_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_synthetics_canary" "some" {
  name                 = "some-canary"
  artifact_s3_location = "s3://some-bucket/"
  execution_role_arn   = "some-role"
  handler              = "exports.handler"
  zip_file             = "test-fixtures/lambdatest.zip"
  runtime_version      = "syn-1.0"

  schedule {
    expression = "rate(0 minute)"
  }
}


# ====================================================================================
# Outputs
# ====================================================================================
output "synthetics_role_arn" { value = aws_iam_role.synthetics.arn }
output "synthetics_policy_arn" { value = aws_iam_policy.synthetics_policy.arn }
output "lambda_role_arn" { value = aws_iam_role.lambda.arn }
output "lambda_policy_arn" { value = aws_iam_policy.lambda_policy.arn }
output "scheduler_role_arn" { value = aws_iam_role.scheduler.arn }

output "canary_name" { value = aws_synthetics_canary.endpoint.name }
output "artifact_bucket" { value = var.artifact_bucket }
output "artifact_prefix" { value = var.artifact_prefix }
