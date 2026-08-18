"""Secret Manager access via the client library (Application Default
Credentials) - works both locally (user ADC) and on Cloud Run (attached
service account), unlike shelling out to the gcloud CLI which isn't
installed in the container image."""
from google.cloud import secretmanager

PROJECT = "driven-backbone-479003-v3"

_client = None


def get_secret(name):
    global _client
    if _client is None:
        _client = secretmanager.SecretManagerServiceClient()
    resource = f"projects/{PROJECT}/secrets/{name}/versions/latest"
    response = _client.access_secret_version(name=resource)
    return response.payload.data.decode("utf-8").strip()
