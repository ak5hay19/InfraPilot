output "bucket_name" {
  description = "Name of the learning S3 bucket (includes the random suffix)."
  value       = aws_s3_bucket.learn.id
}

output "bucket_arn" {
  description = "ARN of the learning S3 bucket, for use in IAM policies."
  value       = aws_s3_bucket.learn.arn
}
