variable "region" {
  description = "AWS region for every resource in this stack."
  type        = string
  default     = "ap-south-1"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "infrapilot"
}
