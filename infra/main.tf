# Terraform + provider setup.
terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# The Google provider authenticates via your Application Default Credentials
# (the same ADC we set up in L1), so no keys live in this file.
provider "google" {
  project = var.project_id
  region  = var.region
}

# A dead-letter topic: Pub/Sub sends messages here after they repeatedly fail
# processing, so a poison message is captured for inspection instead of lost.
# (Codifies the retry/DLQ gap noted back in Level 3.)
resource "google_pubsub_topic" "dead_letter" {
  name    = "document-uploads-dlq"
  project = var.project_id

  labels = {
    managed-by = "terraform"
    component  = "docintel"
  }
}

# The main upload-events topic — created by hand with gcloud in Level 3.
# We declare it here and `terraform import` it, so Terraform now manages it too.
resource "google_pubsub_topic" "uploads" {
  name    = "document-uploads"
  project = var.project_id
}
