variable "region" {
  description = "AWS region for every resource in this stack."
  type        = string
  default     = "ap-south-1"
}

variable "name_prefix" {
  description = "Prefix for resource names. A random suffix is added where names must be globally unique (S3)."
  type        = string
  default     = "infrapilot-learn"
}
