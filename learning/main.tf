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

# Standard queue, same as the console one. Name is deterministic (no suffix)
# because SQS names only need to be unique within this account and region.
# Everything else is left at the provider defaults, which match what the
# console gave you: 30s visibility timeout, 4-day retention, no delay, and
# SSE-SQS encryption on. No DLQ yet; that comes in a later phase.
resource "aws_sqs_queue" "learn" {
  name = "${var.name_prefix}-queue"
}

# Trust policy: WHO may assume this role. Only the Lambda service can.
# A data source reads/computes something; it creates nothing in AWS. This one
# just renders the JSON document, so we don't hand-write a JSON string.
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# The role itself. assume_role_policy is the trust policy; it holds no
# permissions. Reference: .json comes from the data source above, so Terraform
# evaluates that first.
resource "aws_iam_role" "lambda" {
  name               = "${var.name_prefix}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

# Permission 1: attach an AWS-managed policy (logs:CreateLogGroup,
# CreateLogStream, PutLogEvents) so the function can write CloudWatch logs.
# This resource only links role -> policy ARN; the ARN is a fixed string.
# role = aws_iam_role.lambda.name makes the attachment wait for the role.
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Permission 2: WHAT the role may do. Exactly one action on exactly one queue.
# resources = [aws_sqs_queue.learn.arn] is the key reference: Terraform
# creates the queue first and fills in its real ARN. No "*" anywhere, which is
# the fix for the AccessDenied you hit in the console.
data "aws_iam_policy_document" "send_to_queue" {
  statement {
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.learn.arn]
  }
}

# Inline policy: lives inside the role and is deleted with it (unlike a
# standalone managed policy). Depends on both the role and the data document.
resource "aws_iam_role_policy" "send_to_queue" {
  name   = "send-to-learn-queue"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.send_to_queue.json
}
