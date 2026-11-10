output "bucket_name" {
  description = "Name of the learning S3 bucket (includes the random suffix)."
  value       = aws_s3_bucket.learn.id
}

output "bucket_arn" {
  description = "ARN of the learning S3 bucket, for use in IAM policies."
  value       = aws_s3_bucket.learn.arn
}

output "queue_url" {
  description = "URL of the learning SQS queue (what the Lambda sends to)."
  value       = aws_sqs_queue.learn.url
}

output "function_name" {
  description = "Name of the learning Lambda function."
  value       = aws_lambda_function.learn.function_name
}
