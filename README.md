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
  ├ content        (Gemini script generation)
  ├ evaluator hook → agentops-platform
  ├ publisher      (YouTube Shorts upload)
  ├ renderer-stub  (black background + text mp4)
  └ renderer client ──HTTP──> external renderer service (OpenAPI contract in this repo)
```

Stack: ADK / Gemini API / Veo / Imagen / Chirp / Lyria / Cloud Run / BigQuery.

The renderer contract is published as [`api/renderer.openapi.yaml`](./api/renderer.openapi.yaml) (OpenAPI 3.1) — any service implementing its two endpoints can replace the bundled stub.

## Bring your own renderer

The renderer is **pluggable**. The agent talks to it only through the OpenAPI contract (two endpoints), so you can swap the backend without touching the agent:

- **Bundled stub** (ships today) — black background + text mp4, for local/E2E and CI.
- **ffmpeg adapter** (reference, on the [roadmap](./docs/ROADMAP.md)) — minimal, dependency-light, runs anywhere.
- **Remotion adapter** (reference, on the [roadmap](./docs/ROADMAP.md)) — React-based motion graphics for richer output.
- **Your own** — any HTTP service (e.g. Shotstack / Creatomate, or a private studio renderer) that honors the contract.

The contract is intentionally domain-shaped (stock-commentary segments: hook / narration / figures / disclaimer). Only the **renderer backend** is swappable — the agent itself stays specific to one channel and format. Crucially, the safety guarantees live in the *contract*, not in any one backend: figures are rendered exactly (no generative alteration) and a request missing the mandatory disclaimer is rejected — **whichever renderer you plug in**.

## Content generation

Script generation is **pluggable** in the same spirit. This repo bundles **generic example templates** so the pipeline runs end-to-end and the demo is reproducible; a production deployment can swap in its own content generator via config. The agent depends on the *shape* of a script (hook / narration / figures / disclaimer segments), not on any particular template, and the YMYL guards (no recommendation phrasing, mandatory disclaimer) are enforced on the generated script **regardless of which generator produced it**.

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

# 3. Run the E2E pipeline (stub renderer, dry-run publisher)
#    Starts renderer-stub in a background thread and runs script → storyboard → render
pytest tests/test_e2e_pipeline.py -v

# 4. Run the conformance suite (stub, ffmpeg, Remotion adapters)
pytest tests/test_conformance.py -v

# 5. Switch the renderer to the ffmpeg adapter
#    Start the adapter: uvicorn adapters.ffmpeg_adapter.app:app --port 8081
#    Then set RENDERER_URL=http://localhost:8081/v1 in your .env
RENDERER_URL=http://localhost:8081/v1 pytest tests/test_conformance.py -k external
```

### Using your own renderer

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
