"""Smallest possible Vertex AI (Gemini) call — run directly to prove auth + model work."""
import os

from google import genai

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")

# vertexai=True => use Vertex AI backend, authenticated via ADC (the creds we just set).
client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="In one sentence, explain what Google Cloud Run is to a beginner.",
)

print(response.text)
