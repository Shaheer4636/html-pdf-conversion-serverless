terraform {
  required_version = ">= 1.4.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "this" {}
data "aws_partition" "this" {}

# --------------------------------------------
# Canary script packaged into a ZIP (in-memory)
# --------------------------------------------
locals {
  canary_code = <<-JS
    const synthetics = require('Synthetics');
    const log = require('SyntheticsLogger');

    const canaryTest = async function () {
      const url = process.env.TARGET_URL;
      if (!url) { throw new Error("TARGET_URL is not set"); }

      const page = await synthetics.getPage();
      const resp = await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
      const status = resp ? resp.status() : 0;
      log.info("Loaded " + url + " with status " + status);

      if (status < 200 || status > 399) {
        throw new Error("Non-OK HTTP status: " + status);
      }

      await synthetics.takeScreenshot('loaded', 'after_load');
      const title = await page.title();
      if (!title || !title.trim()) {
        throw new Error("Page title is empty");
      }
    };

    exports.handler = async () => {
      return await canaryTest();
    };
  JS
}

data "archive_file" "canary_zip" {
  type                    = "zip"
  source_content          = local.canary_code
  source_content_filename = "index.js"
  # no output_path -> keep it purely in memory for plan/apply
}

# --------------------------------------------
# IAM Role for the Canary (exact name via var)
# --------------------------------------------
resource "aws_iam_role" "synthetics_role" {
  name = var.synthetics_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Principal = { Service = ["lambda.amazonaws.com", "synthetics.amazonaws.com"] },
        Action   = "sts:AssumeRole"
      }
    ]
  })
}

data "aws_iam_policy_document" "synthetics_inline" {
  statement {
    sid     = "LogsAccess"
    effect  = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams"
    ]
    resources = ["*"]
  }

  statement {
    sid     = "PutCWMetrics"
    effect  = "Allow"
    actions = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["CloudWatchSynthetics"]
    }
  }

  statement {
    sid     = "S3ArtifactsWrite"
    effect  = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [
      "arn:${data.aws_partition.this.partition}:s3:::${var.artifacts_bucket_name}",
      "arn:${data.aws_partition.this.partition}:s3:::${var.artifacts_bucket_name}/*"
    ]
  }
}

resource "aws_iam_role_policy" "synthetics_inline" {
  name   = "${var.canary_name}-synthetics-inline"
  role   = aws_iam_role.synthetics_role.id
  policy = data.aws_iam_policy_document.synthetics_inline.json
}

# --------------------------------------------
# CloudWatch Synthetics Canary (every minute)
# --------------------------------------------
resource "aws_synthetics_canary" "this" {
  name                 = var.canary_name
  artifact_s3_location = "s3://${var.artifacts_bucket_name}/${var.canary_name}/"
  execution_role_arn   = aws_iam_role.synthetics_role.arn
  runtime_version      = var.runtime_version
  handler              = "index.handler"
  # FIX: use the archive_file data source output, not filebase64(...)
  zip_file             = data.archive_file.canary_zip.output_base64
  start_canary         = var.start_canary

  schedule {
    expression          = "rate(1 minute)"
    duration_in_seconds = 0
  }

  run_config {
    timeout_in_seconds = var.timeout_seconds
    environment_variables = {
      TARGET_URL = var.target_url
    }
  }

  success_retention_period = var.success_retention_days
  failure_retention_period = var.failure_retention_days

  depends_on = [aws_iam_role_policy.synthetics_inline]
}

output "canary_name" {
  value = aws_synthetics_canary.this.name
}

output "artifacts_prefix" {
  value = "s3://${var.artifacts_bucket_name}/${var.canary_name}/"
}
