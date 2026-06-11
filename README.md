# marketing-shorts-agent

> Individual hackathon entry by Takumi Morimoto — 個人事業（屋号：八雲）として開発・公開

A marketing video agent that produces and publishes Japanese-stock commentary YouTube Shorts for **メイガラシリタイ (メイガラシリタイ)** — and is itself operated, evaluated, and rolled back by [agentops-platform](https://github.com/takumimorimoto-yakumo/agentops-platform) as its demo application.

Built for the DevOps × AI Agent Hackathon 2026.

## What it does

- Generates short-form stock commentary scripts with Gemini (メイガラシリタイ-specific templates)
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

## AI disclosure

This channel is operated by an AI agent and is disclosed as such on YouTube.

## Status

Work in progress (hackathon period: June–July 2026).

## License

Apache-2.0 — Copyright (c) 2026 Takumi Morimoto. See [LICENSE](./LICENSE) and [NOTICE](./NOTICE).
