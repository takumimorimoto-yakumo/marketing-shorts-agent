# Deployment Guide — marketing-shorts-agent

This guide covers deploying the marketing-shorts-agent stack to Cloud Run.
All steps are performed **by a human operator**.

## Services in this repository

| Service | Cloud Run name | Purpose |
|---|---|---|
| Pipeline orchestrator | `marketing-shorts-agent` | Main ADK agent; runs the script→render→publish pipeline |
| Renderer-stub | `renderer-stub` | Bundled stub implementing the renderer contract (for E2E / demo) |

> **Note on the real renderer:** The production renderer is an external private service.
> It implements the same OpenAPI contract (`api/renderer.openapi.yaml`).
> To switch from the stub to the real renderer, set `RENDERER_URL` in the orchestrator
> service to the URL of that private renderer service — no code change is needed.
> The private renderer is not managed by this repository.

---

## Prerequisites

### 1. Google Cloud SDK

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <PROJECT_ID>
```

### 2. APIs to enable

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  youtube.googleapis.com
```

### 3. Artifact Registry repository

```bash
gcloud artifacts repositories create marketing-shorts \
  --repository-format=docker \
  --location=<REGION> \
  --description="marketing-shorts-agent container images"
```

### 4. Service account

```bash
gcloud iam service-accounts create marketing-shorts-sa \
  --display-name="marketing-shorts-agent Cloud Run SA"

# Roles for Cloud Trace / Logging
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:marketing-shorts-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/cloudtrace.agent"

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:marketing-shorts-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Secret Manager (only if you store secrets there)
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:marketing-shorts-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## One-command deploy (via Cloud Build)

Builds both images, pushes to Artifact Registry, and deploys both services:

```bash
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --substitutions=\
_PROJECT_ID=<PROJECT_ID>,\
_REGION=<REGION>,\
_REPO=marketing-shorts,\
_SERVICE_NAME=marketing-shorts-agent,\
_STUB_SERVICE_NAME=renderer-stub,\
_IMAGE_TAG=$(git rev-parse --short HEAD)
```

---

## Manual deploy (shell script)

If images are already in Artifact Registry:

```bash
PROJECT_ID=<PROJECT_ID> \
REGION=<REGION> \
IMAGE_TAG=<TAG> \
  ./deploy/deploy.sh
```

To point the orchestrator at the external private renderer instead of the stub:

```bash
PROJECT_ID=<PROJECT_ID> \
REGION=<REGION> \
IMAGE_TAG=<TAG> \
RENDERER_URL=https://<private-renderer-service-url> \
  ./deploy/deploy.sh
```

---

## Environment variables

### Pipeline orchestrator (`marketing-shorts-agent`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | yes | — | GCP project id |
| `GOOGLE_CLOUD_REGION` | yes | — | Cloud Run region |
| `RENDERER_URL` | yes | — | URL of the renderer service (stub or private) |
| `AGENTOPS_BASE_URL` | yes | — | Base URL of the agentops-platform service |
| `AGENTOPS_AGENT_ID` | no | `marketing-shorts-agent` | Agent id registered with the platform |
| `GEMINI_SCRIPT_MODEL` | no | `gemini-2.5-flash` | Gemini model for script generation |
| `GEMINI_STORYBOARD_MODEL` | no | `gemini-2.5-flash` | Gemini model for storyboard generation |
| `GEMINI_EVAL_MODEL` | no | `gemini-2.5-flash` | Gemini model for YMYL evaluation |
| `VEO_MODEL` | no | `veo-3.0-generate-preview` | Veo model id |
| `IMAGEN_MODEL` | no | `imagen-3.0-generate-001` | Imagen model id |
| `CHIRP_VOICE` | no | `ja-JP-Standard-D` | Chirp voice id |
| `LYRIA_MODEL` | no | `lyria-2` | Lyria model id |
| `DRY_RUN` | no | `true` | `true` = skip actual YouTube upload |
| `LOG_LEVEL` | no | `INFO` | Log verbosity |

### Renderer-stub (`renderer-stub`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOG_LEVEL` | no | `INFO` | Log verbosity |

### Secrets (Secret Manager)

| Secret name (suggested) | Env var | Description |
|---|---|---|
| `agentops-api-key` | `AGENTOPS_API_KEY` | API key for agentops-platform |
| `youtube-channel-id` | `YOUTUBE_CHANNEL_ID` | YouTube channel to publish to |
| `youtube-client-secrets` | `YOUTUBE_CLIENT_SECRETS_FILE` | OAuth credentials JSON for YouTube API |

Attach secrets to the Cloud Run service via `--update-secrets` or `deploy/service-orchestrator.yaml`.
Secret values are **never** embedded in environment variable configs.

---

## Verify the deployment

```bash
# Get service URLs
gcloud run services describe marketing-shorts-agent \
  --region=<REGION> --format="value(status.url)"

gcloud run services describe renderer-stub \
  --region=<REGION> --format="value(status.url)"

# Health check the stub (internal; needs a bearer token if --no-allow-unauthenticated)
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer ${TOKEN}" https://<STUB_URL>/healthz
```

---

## Renderer backend switching

The orchestrator selects the renderer purely via `RENDERER_URL`:

| Mode | `RENDERER_URL` value |
|---|---|
| Local development | *(empty — falls back to stub running locally)* |
| E2E / demo on Cloud Run | URL of the `renderer-stub` Cloud Run service |
| Production | URL of the private renderer service |

No code change is required to switch; update the environment variable in the Cloud Run console or via `gcloud run services update --update-env-vars`.

---

## Service configuration reference

- `deploy/service-orchestrator.yaml` — full spec for the pipeline orchestrator
- `deploy/service-renderer-stub.yaml` — full spec for the renderer-stub
