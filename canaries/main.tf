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


resource "aws_s3_bucket" "artifacts" {
  bucket = var.artifacts_bucket_name
}

# Optional server-side encryption for artifacts
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block public access (recommended)
resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


resource "aws_iam_role" "synthetics_role" {
  name = var.synthetics_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = [
            "lambda.amazonaws.com",
            "synthetics.amazonaws.com"
          ]
        },
        Action = "sts:AssumeRole"
      }
    ]
  })
}

# Policy granting CloudWatch Logs, Metrics, and S3 write to your artifacts bucket
data "aws_iam_policy_document" "synthetics_inline" {
  statement {
    sid     = "Logs"
    effect  = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.this.account_id}:log-group:/aws/lambda/cwsyn-*:*"]
  }

  statement {
    sid     = "Metrics"
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
    sid     = "S3WriteArtifacts"
    effect  = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetBucketLocation",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*"
    ]
  }
}

resource "aws_iam_role_policy" "synthetics_inline" {
  name   = "${var.canary_name}-synthetics-inline"
  role   = aws_iam_role.synthetics_role.id
  policy = data.aws_iam_policy_document.synthetics_inline.json
}

data "aws_caller_identity" "this" {}


# Minimal heartbeat that loads the URL and asserts 2xx/3xx status.
# Uses TARGET_URL as env var.
locals {
  canary_code = <<'JS'
const synthetics = require('Synthetics');
const log = require('SyntheticsLogger');

const canaryTest = async function () {
  const url = process.env.TARGET_URL;
  if (!url) throw new Error("TARGET_URL is not set");

  const page = await synthetics.getPage();

  // Navigate and wait for network to be idle
  const resp = await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
  const status = resp ? resp.status() : 0;
  log.info(`Loaded ${url} with status ${status}`);

  if (status < 200 || status > 399) {
    throw new Error(`Non-OK HTTP status: ${status}`);
  }

  await synthetics.takeScreenshot('loaded', 'after_load');
  // Simple content sanity: page has a title
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
  type                        = "zip"
  source_content              = local.canary_code
  source_content_filename     = "index.js"
  output_path                 = "${path.module}/canary.zip"
}


resource "aws_synthetics_canary" "this" {
  name                 = var.canary_name
  artifact_s3_location = "s3://${aws_s3_bucket.artifacts.bucket}/${var.canary_name}/"
  execution_role_arn   = aws_iam_role.synthetics_role.arn
  runtime_version      = var.runtime_version
  handler              = "index.handler"
  start_canary         = var.start_canary

  schedule {
    expression = "rate(1 minute)"
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

  depends_on = [
    aws_iam_role_policy.synthetics_inline
  ]
}

# Optional: Output useful values
output "canary_name" {
  value = aws_synthetics_canary.this.name
}

output "artifacts_prefix" {
  value = "s3://${aws_s3_bucket.artifacts.bucket}/${var.canary_name}/"
}
