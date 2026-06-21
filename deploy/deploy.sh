#!/usr/bin/env bash
# deploy/deploy.sh — Deploy marketing-shorts-agent services to Cloud Run.
#
# This script deploys two services:
#   1. renderer-stub           — bundled stub renderer
#   2. marketing-shorts-agent  — pipeline orchestrator (depends on renderer-stub URL)
#
# The real renderer is an external private service.  To switch, set RENDERER_URL
# to that service's URL; the orchestrator will route render requests there instead.
#
# This script does NOT build or push images.  Use Cloud Build (cloudbuild.yaml).
#
# Required environment variables:
#   PROJECT_ID        GCP project id
#   REGION            Cloud Run region (e.g. us-central1)
#
# Optional environment variables (have defaults):
#   SERVICE_NAME      Orchestrator service name (default: marketing-shorts-agent)
#   STUB_SERVICE_NAME Renderer-stub service name (default: renderer-stub)
#   IMAGE_TAG         Container image tag (default: latest)
#   REPO              Artifact Registry repository name (default: marketing-shorts)
#   RENDERER_URL      URL of the renderer service.
#                     If empty, the stub is deployed first and its URL is used.
#                     Set this to the private renderer URL to bypass the stub.
#
# Usage:
#   PROJECT_ID=my-project REGION=us-central1 ./deploy/deploy.sh

set -euo pipefail

# ── Resolve configuration ─────────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:?PROJECT_ID is required}"
REGION="${REGION:?REGION is required}"
SERVICE_NAME="${SERVICE_NAME:-marketing-shorts-agent}"
STUB_SERVICE_NAME="${STUB_SERVICE_NAME:-renderer-stub}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REPO="${REPO:-marketing-shorts}"

BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"

# ── Deploy renderer-stub ──────────────────────────────────────────────────────
echo "==> Deploying ${STUB_SERVICE_NAME} …"

gcloud run deploy "${STUB_SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --image="${BASE}/${STUB_SERVICE_NAME}:${IMAGE_TAG}" \
  --no-allow-unauthenticated \
  --command="uvicorn" \
  --args="renderer_stub.app:app,--host,0.0.0.0,--port,8080" \
  --memory=512Mi \
  --cpu=1 \
  --concurrency=80 \
  --min-instances=0 \
  --max-instances=5 \
  --update-env-vars="LOG_LEVEL=INFO"

STUB_URL=$(gcloud run services describe "${STUB_SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(status.url)")

echo "    ${STUB_SERVICE_NAME} URL: ${STUB_URL}"

# ── Resolve RENDERER_URL ──────────────────────────────────────────────────────
# If RENDERER_URL is not set, fall back to the stub we just deployed.
# To route to the external private renderer service, export RENDERER_URL before
# calling this script.
RENDERER_URL="${RENDERER_URL:-${STUB_URL}}"
echo "==> RENDERER_URL resolved to: ${RENDERER_URL}"

# ── Deploy orchestrator ───────────────────────────────────────────────────────
echo "==> Deploying ${SERVICE_NAME} …"

DEPLOY_ARGS=(
  run deploy "${SERVICE_NAME}"
  "--project=${PROJECT_ID}"
  "--region=${REGION}"
  "--platform=managed"
  "--image=${BASE}/${SERVICE_NAME}:${IMAGE_TAG}"
  "--no-allow-unauthenticated"
  "--command=uvicorn"
  "--args=marketing_shorts_agent.main:app,--host,0.0.0.0,--port,8080"
  "--memory=1Gi"
  "--cpu=1"
  "--concurrency=10"
  "--min-instances=0"
  "--max-instances=5"
  "--update-env-vars=GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
  "--update-env-vars=GOOGLE_CLOUD_REGION=${REGION}"
  "--update-env-vars=DRY_RUN=false"
  "--update-env-vars=LOG_LEVEL=INFO"
  "--update-env-vars=RENDERER_URL=${RENDERER_URL}"
)

# ── Attach Secret Manager secrets ─────────────────────────────────────────────
# Secret values are NEVER set as plain text here.
#
# Example — uncomment and fill in your secret resource paths:
#   DEPLOY_ARGS+=(
#     "--update-secrets=AGENTOPS_API_KEY=projects/<id>/secrets/agentops-api-key/versions/latest"
#     "--update-secrets=YOUTUBE_CLIENT_SECRETS_FILE=projects/<id>/secrets/yt-client-secrets/versions/latest"
#   )
#
# if [[ -n "${SECRET_AGENTOPS_API_KEY_VERSION:-}" ]]; then
#   DEPLOY_ARGS+=("--update-secrets=AGENTOPS_API_KEY=${SECRET_AGENTOPS_API_KEY_VERSION}")
# fi

gcloud "${DEPLOY_ARGS[@]}"

ORCHESTRATOR_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(status.url)")

echo ""
echo "==> Deployment complete."
echo "    ${SERVICE_NAME}:  ${ORCHESTRATOR_URL}"
echo "    ${STUB_SERVICE_NAME}: ${STUB_URL}"
