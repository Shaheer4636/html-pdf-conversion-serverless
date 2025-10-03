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

# Optional short random suffix to guarantee global uniqueness
resource "random_id" "suffix" {
  count       = var.add_random_suffix ? 1 : 0
  byte_length = 2
}

# locals (drop all regexreplace/trim usage)
locals {
  # Prefix with optional short random suffix, then lowercase
  unique_prefix = lower(
    var.add_random_suffix
      ? "${var.name_prefix}-${random_id.suffix[0].hex}"
      : var.name_prefix
  )

  # Build raw names
  canary_name_raw = "${local.unique_prefix}-${var.canary_bucket_name}"
  report_name_raw = "${local.unique_prefix}-${var.report_bucket_name}"

  # Normalize: spaces/underscores → hyphens; lowercase
  canary_name_norm = replace(replace(lower(local.canary_name_raw), " ", "-"), "_", "-")
  report_name_norm = replace(replace(lower(local.report_name_raw), " ", "-"), "_", "-")

  # Enforce 63-char S3 bucket limit
  canary_bucket_name = substr(local.canary_name_norm, 0, 63)
  report_bucket_name = substr(local.report_name_norm, 0, 63)
}


# ---------------------------
# Canary artifacts bucket
# ---------------------------
resource "aws_s3_bucket" "canary" {
  bucket        = local.canary_bucket_name
  force_destroy = var.force_destroy
  tags          = merge(local.common_tags, { Name = local.canary_bucket_name })
}

resource "aws_s3_bucket_public_access_block" "canary" {
  bucket                  = aws_s3_bucket.canary.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "canary" {
  bucket = aws_s3_bucket.canary.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_versioning" "canary" {
  bucket = aws_s3_bucket.canary.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "canary" {
  bucket = aws_s3_bucket.canary.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---------------------------
# Report output bucket
# ---------------------------
resource "aws_s3_bucket" "report" {
  bucket        = local.report_bucket_name
  force_destroy = var.force_destroy
  tags          = merge(local.common_tags, { Name = local.report_bucket_name })
}

resource "aws_s3_bucket_public_access_block" "report" {
  bucket                  = aws_s3_bucket.report.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "report" {
  bucket = aws_s3_bucket.report.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_versioning" "report" {
  bucket = aws_s3_bucket.report.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "report" {
  bucket = aws_s3_bucket.report.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---------------------------
# Outputs
# ---------------------------
output "canary_bucket_name" { value = aws_s3_bucket.canary.bucket }
output "canary_bucket_arn"  { value = aws_s3_bucket.canary.arn }
output "report_bucket_name" { value = aws_s3_bucket.report.bucket }
output "report_bucket_arn"  { value = aws_s3_bucket.report.arn }
output "unique_prefix"      { value = local.unique_prefix }
