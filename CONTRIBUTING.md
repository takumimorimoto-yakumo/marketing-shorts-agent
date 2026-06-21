# Contributing to marketing-shorts-agent

Thank you for your interest in contributing.

## Development environment

Requires Python 3.11+ and (optionally) Node.js 20+ for the Remotion adapter.

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install the package and dev dependencies
pip install -e ".[dev]"
```

Environment variables: copy `.env.example` to `.env` and fill in the values you
need. For local tests and E2E the defaults (empty `RENDERER_URL`, `DRY_RUN=true`)
are sufficient.

## Running tests

```bash
# All unit + integration tests (no network required)
pytest

# Conformance suite only — stub, ffmpeg, and Remotion adapters
pytest tests/test_conformance.py

# Conformance suite against a live external renderer
RENDERER_URL=http://localhost:8081/v1 pytest tests/test_conformance.py -k external

# E2E pipeline (starts renderer-stub in a background thread)
pytest tests/test_e2e_pipeline.py
```

All tests must pass before opening a pull request.

## Running the renderer-stub locally

```bash
# Start renderer-stub on port 8080 (default)
uvicorn renderer_stub.app:app --port 8080

# Or run a reference adapter
uvicorn adapters.ffmpeg_adapter.app:app --port 8081
uvicorn adapters.remotion_adapter.app:app --port 8082
```

## Code style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
ruff check .
ruff format .
```

Static type checking with mypy:

```bash
mypy src/
```

## Branch and PR conventions

- Work on a feature branch cut from `develop`.
- Target pull requests against `develop` (never `main`).
- Keep commits focused and use imperative-mood messages in English
  (e.g. `fix: escape commas in ffmpeg drawtext filter`).
- Include or update tests for any behaviour change.

## YMYL and content guard rules

The YMYL guards (`src/marketing_shorts_agent/guards/ymyl.py`) are **real
enforcement** and must not be weakened or bypassed. Any PR that removes a
guard, lowers detection coverage, or introduces stock-recommendation phrasing
in templates will be declined.

## Renderer contract

The renderer contract is defined in `api/renderer.openapi.yaml` (OpenAPI 3.1).
Any change to the contract must bump the version according to the versioning
policy described in that file (minor for backward-compatible additions, major
for breaking changes).

New renderer backends must pass the full conformance suite
(`tests/test_conformance.py`) before being accepted.

## License

By submitting a pull request you agree that your contribution is licensed under
the Apache-2.0 license, consistent with the rest of this project.
