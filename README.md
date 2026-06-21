# marketing-shorts-agent

> Individual hackathon entry by Takumi Morimoto — 個人事業（屋号：八雲）として開発・公開

A marketing video agent that produces and publishes Japanese-stock commentary YouTube Shorts for **メイガラシリタイ** — and is itself operated, evaluated, and rolled back by [agentops-platform](https://github.com/takumimorimoto-yakumo/agentops-platform) as its demo application.

Built for the DevOps × AI Agent Hackathon 2026.

## What it does

- Generates short-form stock commentary scripts with Gemini from pluggable templates (generic examples bundled)
- Renders videos via an external renderer service over HTTP (a stub renderer — black background + text mp4 — is bundled so the pipeline runs end-to-end)
- Publishes to YouTube Shorts and feeds Analytics back into agentops-platform's evaluation loop
- Enforces YMYL guards: no stock recommendations (template-level + Gemini eval detection), mandatory disclaimer captions, official primary data sources only (EDINET / J-Quants)

This repository is intentionally **specific to メイガラシリタイ**: one channel, one format, short-form only.

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
  ├ evaluator hook → agentops-platform
  └ publisher      (YouTube Shorts upload)
```

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
