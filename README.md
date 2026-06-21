# marketing-shorts-agent

> Individual hackathon entry by Takumi Morimoto — 個人事業（屋号：八雲）として開発・公開

A marketing video agent that produces and publishes Japanese-stock commentary YouTube Shorts for **メイガラシリタイ** — and is itself operated, evaluated, and rolled back by [agentops-platform](https://github.com/takumimorimoto-yakumo/agentops-platform) as its demo application.

Built for the DevOps × AI Agent Hackathon 2026.

## What it does

- Generates short-form stock commentary scripts with Gemini (channel-specific templates)
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

## AI disclosure

This channel is operated by an AI agent and is disclosed as such on YouTube.

## Status

Work in progress (hackathon period: June–July 2026).

## License

Apache-2.0 — Copyright (c) 2026 Takumi Morimoto. See [LICENSE](./LICENSE) and [NOTICE](./NOTICE).
