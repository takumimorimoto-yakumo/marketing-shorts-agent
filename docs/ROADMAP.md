# marketing-shorts-agent — Build Roadmap

Implementation SSOT: what to build, in what order, with acceptance criteria, so a
fresh session can pick up any milestone. Keep it technical and public-safe.

## Goal (one sentence)

An autonomous agent that produces Japanese-stock commentary YouTube Shorts for
メイガラシリタイ, publishes them, feeds Analytics back to agentops-platform, and is itself
evaluated / canaried / rolled back by that platform as a managed agent.

## Role in the larger system

This agent is the **demo application** for agentops-platform. It is a *managed
agent*: each script/prompt version is registered with the platform, rolled out by
canary, and subject to autonomous rollback. The reproducible end-to-end story is:
a regressed script version is deployed → the platform's meta-agent detects the
drop → it is rolled back autonomously. This repo's job is to be a real, running
agent good enough to be operated that way.

## Content guard (YMYL — highest priority, never regress)

- No stock-recommendation phrasing (enforced at template level + detected by Gemini eval)
- Mandatory disclaimer caption/segment on every video
- Primary official data only (EDINET / J-Quants); no company logos, use tickers
- AI operation is disclosed on YouTube

## Scope (MVP)

| In | Out |
|---|---|
| Per-stock commentary Shorts generation + YouTube upload | Long-form video |
| Gemini script generation (channel-specific templates) | Generic video schema / abstraction layers |
| Pull YouTube Analytics → push to agentops-platform `/metrics` | A self-improvement loop of its own (lives in the platform) |
| YMYL guards (no-recommendation, disclaimer, primary data) | Multi-agent orchestration |
| Bundled renderer-stub (black background + text mp4) for E2E | The real renderer (external private HTTP service) |

## Architecture / components

```
pipeline orchestrator (ADK on Cloud Run)
  ├ content        (Gemini script generation, channel templates)
  ├ renderer client ──HTTP──> external renderer service (contract: api/renderer.openapi.yaml)
  │                            (renderer-stub bundled here for local/E2E)
  ├ publisher      (YouTube Shorts upload + AI disclosure)
  ├ analytics      (pull retention etc. → POST agentops /agents/{id}/metrics)
  └ version register (register script/prompt version with agentops-platform)
```

## Milestones (ordered; each has an acceptance test)

- **M1 — Script generation.** Gemini + channel templates produce a structured script
  (hook / figures / commentary / disclaimer). *Accept:* a script object that always
  contains a disclaimer segment and passes the no-recommendation check.
- **M2 — Renderer client + stub E2E.** Call the renderer contract; bundled stub
  returns a black+text mp4. *Accept:* script → mp4 end to end with the stub; a
  request missing the disclaimer segment is rejected.
- **M3 — Publisher.** Upload to YouTube Shorts with AI disclosure set. *Accept:* a
  test video publishes (private/unlisted) with disclosure flag.
- **M4 — Register + metrics loop.** Register the version with agentops-platform;
  pull Analytics and push to `/metrics`. *Accept:* a published version appears as a
  managed version in the platform and a retention metric lands via `/metrics`.
- **M5 — Be the rollback subject.** Wire a "broken script version" path so the
  platform can canary and roll it back. *Accept:* the platform's reproducible
  rollback demo runs against this agent.
- **M6 — Real renderer cutover.** Point the renderer client at the external service
  (replacing the stub) via config. *Accept:* a real rendered Short publishes.

## Renderer contract boundary

- The renderer is an external service. Contract = `api/renderer.openapi.yaml`
  (published here, OpenAPI 3.1). Any service implementing it can replace the stub.
- Audio: the renderer generates Veo clips with audio off by default and composes
  Chirp narration + Lyria BGM, so spoken stock names/figures stay exact. The client
  only sends segment intents; audio handling lives behind the contract.

## Tech stack

ADK + Gemini API / Veo / Imagen / Chirp / Lyria / Cloud Run / BigQuery.
No dependency on external LLMs.

## Config SSOT (no hard-coding)

- Script templates / disclaimer text → `config/templates/`
- Renderer API endpoint → `.env.example` + config layer
- Gemini / Veo model ids → config layer (never inline in code)
