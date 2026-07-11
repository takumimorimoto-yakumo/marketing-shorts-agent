# marketing-shorts-agent

> Individual hackathon entry by Takumi Morimoto — 個人事業（屋号：八雲）として開発・公開

A marketing video agent that produces and publishes Japanese-stock commentary YouTube Shorts for **メイガラシリタイ** — and is itself operated, evaluated, and rolled back by [agentops-platform](https://github.com/takumimorimoto-yakumo/agentops-platform) as its demo application.

Built for the DevOps × AI Agent Hackathon 2026.

## What it does

- Generates short-form stock commentary scripts with Gemini from pluggable templates (generic examples bundled)
- Renders videos via an external renderer service over HTTP (a stub renderer — black background + text mp4 — is bundled so the pipeline runs end-to-end)
- **Autonomously evaluates its own rendered videos** with a two-layer Video QA stage (deterministic ffprobe checks + Gemini multimodal visual judgment) and blocks publishing on failure — a self-managing agent that governs its own output quality
- Publishes to YouTube Shorts and feeds Analytics back into agentops-platform's evaluation loop, including Video QA outcome metrics
- Enforces YMYL guards: no stock recommendations (template-level + Gemini eval detection), mandatory disclaimer captions, official primary data sources only (EDINET / J-Quants)

This repository is intentionally **specific to メイガラシリタイ**: one channel, one format, short-form only.

## Relationship to agentops-platform

This is a **managed agent**: it does the real task (making Shorts) and is *operated* by [agentops-platform](https://github.com/takumimorimoto-yakumo/agentops-platform). The platform does not use this agent's videos — it governs this agent's *behavior* (evaluate → canary → auto-rollback).

```
   agentops-platform        (control plane + autonomous meta-agent)
        │  ▲
   (1)  │  │  (2)
 operate │  │ report
  / eval ▼  │
   marketing-shorts-agent   (this repo — does the real task)
        │
        ▼  the Shorts go to YouTube / viewers — the platform never consumes them
```

- **(1) platform → this agent**: evaluates each script/prompt version, rolls it out by canary, and auto-rolls-back on regression.
- **(2) this agent → platform**: registers its versions and pushes outcome metrics (audience retention / ROAS).

## Architecture

```
[ marketing-shorts-agent ]
  ├ pipeline orchestrator (ADK on Cloud Run)
  │
  ├ content client ──HTTP──> content service  (OpenAPI contract: api/content.openapi.yaml)
  │                           (content-stub bundled for local/E2E and CI)
  │
  ├ storyboard client ──HTTP──> storyboard service  (OpenAPI contract: api/storyboard.openapi.yaml)
  │                              (storyboard-stub bundled for local/E2E and CI)
  │
  ├ renderer client ──HTTP──> renderer service  (OpenAPI contract: api/renderer.openapi.yaml)
  │                            (renderer-stub bundled for local/E2E and CI)
  │
  ├ video QA (self-evaluation gate — fail-closed)
  │   Layer 1 — deterministic: ffprobe stream/duration checks, black/white frame detection
  │   Layer 2 — visual LLM:    sampled frames → Gemini multimodal rubric (text legibility /
  │                             layout / readability), structured JSON output
  │   Gate: QA fail or error → publish skipped; QA metrics pushed to agentops-platform
  │
  ├ evaluator hook → agentops-platform
  └ publisher      (YouTube Shorts upload; only reached when Video QA passes)
```

### Pipeline stages

| # | Stage | Description |
|---|---|---|
| 1 | Content generation | Script via HTTP content service or bundled stub |
| 2 | YMYL guard (script) | Disclaimer presence + no stock-recommendation phrasing |
| 3 | Evaluator hook | Trajectory / drift scoring via agentops-platform |
| 4 | Storyboard generation | Storyboard via HTTP storyboard service or bundled stub |
| 5 | YMYL guard (storyboard) | Same rules applied to the rendered storyboard |
| 6 | Renderer | Submit storyboard + wait for render job to complete |
| 7 | **Video QA** | **Fail-closed self-evaluation: deterministic ffprobe checks + Gemini visual judgment (see below)** |
| 8 | Publisher | YouTube Shorts upload (dry-run by default; **skipped if Video QA fails**) |
| 9 | Version register | Register agent version with agentops-platform |
| 10 | Analytics push | Push outcome metrics to agentops-platform (**includes QA verdict metrics**) |

### Video QA stage (stage 7)

The agent autonomously evaluates the video it just rendered before deciding whether to publish.

**Layer 1 — Deterministic checks (no LLM, always run):**
- Video stream present (ffprobe JSON probe)
- Duration within ±20 % of expected value
- No fully-black frames (luminance mean ≤ 10 at 10 / 50 / 90 % of duration)
- No fully-white frames (luminance mean ≥ 245 at same sample points)

**Layer 2 — Visual LLM judgment (Gemini multimodal, when deterministic checks pass):**
- Three frames sampled from the video (10 / 50 / 90 % of duration)
- Sent to Gemini with a structured rubric prompt
- Scored on: `text_legibility`, `layout`, `readability` (each 0.0–1.0)
- Structured JSON output parsed deterministically — no free-form text

**Gate behaviour (fail-closed):**
- Any deterministic check fails → FAIL, publish skipped
- Deterministic checks pass, visual check fails → FAIL, publish skipped
- QA infrastructure error → ERROR, publish skipped (never silently unblocked)

**agentops metrics pushed** (numeric, per run): `video_qa_pass`, `video_qa_video_stream_present`, `video_qa_duration_in_range`, `video_qa_no_black_frames`, `video_qa_no_white_frames`, `video_qa_visual_pass`, `video_qa_visual_text_legibility`, `video_qa_visual_layout`, `video_qa_visual_readability`.

**Environment variables:**
| Variable | Default | Description |
|---|---|---|
| `VIDEO_QA_USE_GEMINI` | `false` | `true` → real ffprobe + Gemini checks; `false` → stub (always passes) |
| `VIDEO_QA_GEMINI_BACKEND` | `genai` | `genai` (google-generativeai) or `vertex` (Vertex AI). ADC only — no API key. |

Stack: ADK / Gemini API / Veo / Imagen / Chirp / Lyria / Cloud Run / BigQuery.

All three generation services (content, storyboard, renderer) are external HTTP services behind
published OpenAPI 3.1 contracts.  Bundled stubs ship with this repo so the full pipeline runs
end-to-end without any private dependency.

## Bring your own content / storyboard / renderer

All three generation services are **pluggable**.  The agent talks to each one only through its
OpenAPI contract, so you can swap any backend without touching the agent code.  Set the
corresponding URL in your environment:

| Service | Env var | Bundled stub | Contract |
|---|---|---|---|
| Content (script generation) | `CONTENT_URL` | `content-stub` (template-based, no LLM) | `api/content.openapi.yaml` |
| Storyboard | `STORYBOARD_URL` | `storyboard-stub` (template-based, no LLM) | `api/storyboard.openapi.yaml` |
| Renderer | `RENDERER_URL` | `renderer-stub` (black background + text mp4) | `api/renderer.openapi.yaml` |

Leave any URL empty and the corresponding bundled stub starts in-process automatically.

**Renderer adapters:**
- **Bundled stub** (ships today) — black background + text mp4, for local/E2E and CI.
- **ffmpeg adapter** (reference, on the [roadmap](./docs/ROADMAP.md)) — minimal, dependency-light, runs anywhere.
- **Remotion adapter** (reference, on the [roadmap](./docs/ROADMAP.md)) — React-based motion graphics for richer output.
- **Your own** — any HTTP service that honors the contract.

All three contracts are intentionally domain-shaped (stock-commentary segments: hook / narration / figures / disclaimer).  The safety guarantees live in the *contracts*, not in any one backend: figures are reproduced exactly (no generative alteration) and a request missing the mandatory disclaimer is rejected — **whichever backend you plug in**.

## Content generation

Script and storyboard generation are **pluggable** behind HTTP contracts (see above).  This repo
bundles **generic example stubs** (template-based, no LLM) so the pipeline runs end-to-end and
the demo is reproducible.  A production deployment points `CONTENT_URL` / `STORYBOARD_URL` at its
own private service.  The agent depends only on the *shape* of a Script and Storyboard (hook /
narration / figures / disclaimer), and the YMYL guards (no recommendation phrasing, mandatory
disclaimer) are enforced on the output **regardless of which service produced it**.

## AI disclosure

This channel is operated by an AI agent and is disclosed as such on YouTube.

## Quickstart

Requires Python 3.11+.

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Run all tests (no network, no credentials required)
pytest

# 3. Run the E2E pipeline (all bundled stubs — content, storyboard, renderer — start in-process)
#    No external services required.
pytest tests/test_e2e_pipeline.py -v

# 4. Run the conformance suite (stub, ffmpeg, Remotion adapters)
pytest tests/test_conformance.py -v

# 5. Run the content-stub / storyboard-stub contract tests
pytest tests/test_content_stub.py tests/test_storyboard_stub.py -v

# 6. Switch the renderer to the ffmpeg adapter
#    Start the adapter: uvicorn adapters.ffmpeg_adapter.app:app --port 8081
#    Then set RENDERER_URL=http://localhost:8081/v1 in your .env
RENDERER_URL=http://localhost:8081/v1 pytest tests/test_conformance.py -k external
```

### Using your own content / storyboard / renderer services

Set the corresponding URL env var to any HTTP service that implements the published contract,
and the pipeline will use it instead of the bundled stub:

```bash
CONTENT_URL=https://your-content-service/v1
STORYBOARD_URL=https://your-storyboard-service/v1
RENDERER_URL=https://your-renderer-service/v1
```

Each URL is independent — mix and match bundled stubs and external services freely.

### Using your own renderer (legacy section)

Set `RENDERER_URL` to any HTTP service that implements the two endpoints in
[`api/renderer.openapi.yaml`](./api/renderer.openapi.yaml) and the pipeline
will use it instead of the bundled stub. The contract is intentionally minimal:
POST a storyboard, poll for the result.

### Plugging in your own content generator

Set `content_generator` in `PipelineConfig` to any object implementing
`ContentGeneratorInterface` (see `src/marketing_shorts_agent/content/interface.py`).
The bundled `ExampleContentGenerator` is a generic reference implementation;
production deployments swap it for a channel-specific generator via config.

## Status

Work in progress (hackathon period: June–July 2026).

## License

Apache-2.0 — Copyright (c) 2026 Takumi Morimoto. See [LICENSE](./LICENSE) and [NOTICE](./NOTICE).
