terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region

  # Applied automatically to every taggable resource this provider creates.
  # This is the only place the project tag is set; no per-resource tags.
  default_tags {
    tags = {
      project = "infrapilot"
    }
  }
}

# S3 bucket names are global across all AWS accounts, so a fixed name would
# likely collide. 4 random bytes -> 8 lowercase hex chars (valid in a bucket name).
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "learn" {
  bucket = "${var.name_prefix}-${random_id.bucket_suffix.hex}"
}

# Same as the four "Block all public access" checkboxes in the console.
resource "aws_s3_bucket_public_access_block" "learn" {
  bucket = aws_s3_bucket.learn.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
