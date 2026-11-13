# Single table: plays, profiles and group membership, organised by person and by group.
#   USER#<id>   / PROFILE                      sync cursor, last sync status, display name
#   USER#<id>   / PLAY#<played_at>#<track_id>  one item per play
#   GROUP#<id>  / MEMBER#<user_id>             who belongs to the group
resource "aws_dynamodb_table" "main" {
  name         = var.name
  billing_mode = "PAY_PER_REQUEST" # on-demand: we write a few hundred items a day, capacity planning makes no sense
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # The listening history cannot be fetched again from Spotify: it must survive mistakes.
  deletion_protection_enabled = var.protect_data

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true # AWS managed KMS key (aws/dynamodb): key usage shows up in CloudTrail
  }
}

# Raw Spotify responses (data lake raw zone). Kept so the statistics can be rebuilt if the
# table schema changes, and read later by Glue/Athena. Keys are Hive-style partitions:
#   raw/provider=spotify/user=<id>/dt=<yyyy-mm-dd>/<hhmmss>.json
resource "aws_s3_bucket" "raw" {
  count         = var.existing_raw_bucket == "" ? 1 : 0
  bucket_prefix = "${var.name}-raw-"
  force_destroy = !var.protect_data
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = local.raw_bucket_name
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "raw" {
  bucket = local.raw_bucket_name
  rule {
    object_ownership = "BucketOwnerEnforced" # ACLs disabled
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = local.raw_bucket_name
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.customer_managed_key ? "aws:kms" : "AES256"
      kms_master_key_id = local.kms_key_arn
    }
    bucket_key_enabled = var.customer_managed_key # one KMS call per bucket key, not per object
  }
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = local.raw_bucket_name
  versioning_configuration {
    status = "Enabled" # an overwrite or delete by mistake can be undone
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = local.raw_bucket_name

  rule {
    id     = "archive-old-raw-data"
    status = "Enabled"

    filter {
      prefix = "raw/"
    }

    # Old raw files are only read when rebuilding everything: cheaper storage, still instant access.
    transition {
      days          = 180
      storage_class = "GLACIER_IR"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.raw]
}

data "aws_iam_policy_document" "raw_tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [local.raw_bucket_arn, "${local.raw_bucket_arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "raw" {
  bucket     = local.raw_bucket_name
  policy     = data.aws_iam_policy_document.raw_tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.raw]
}

locals {
  raw_bucket_name = var.existing_raw_bucket != "" ? var.existing_raw_bucket : aws_s3_bucket.raw[0].id
  raw_bucket_arn  = "arn:${local.partition}:s3:::${local.raw_bucket_name}"
}

moved {
  from = aws_s3_bucket.raw
  to   = aws_s3_bucket.raw[0]
}
