# Input variables — values can be overridden per-environment.
variable "project_id" {
  type        = string
  description = "The GCP project to manage."
  default     = "docintel-srg-2026"
}

variable "region" {
  type        = string
  description = "Default region for regional resources."
  default     = "us-central1"
}
