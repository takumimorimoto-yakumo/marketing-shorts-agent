"""FastAPI application entry point for marketing-shorts-agent.

Start with::

    uvicorn marketing_shorts_agent.main:app --host 0.0.0.0 --port 8080

Environment variables (see deploy/DEPLOY.md for full reference):

RENDERER_URL
    Base URL of the renderer service, e.g. ``https://renderer.run.app/v1``.
    Empty → the bundled renderer-stub is started in-process automatically.
CONTENT_URL
    Base URL of the content service.  Empty → bundled content-stub.
STORYBOARD_URL
    Base URL of the storyboard service.  Empty → bundled storyboard-stub.
AGENTOPS_BASE_URL
    Base URL of the agentops-platform.  Empty → agentops integration is
    skipped; stub implementations are used for evaluator, analytics, and
    version register (matching the existing PipelineConfig defaults).
DRY_RUN
    ``true`` (default) → the publisher skips the actual YouTube upload and
    returns a mock PublishResult.  Set to ``false`` in production when real
    YouTube credentials are provided.
LOG_LEVEL
    Python log level string (default ``INFO``).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .content import StockInfo
from .models import FigureItem
from .pipeline import PipelineConfig, PipelineOrchestrator, PipelineResult

# ── Logging setup ─────────────────────────────────────────────────────────────

_LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

# ── Request / response models ─────────────────────────────────────────────────


class StockInfoRequest(BaseModel):
    """Request body for ``POST /pipeline/run``.

    Mirrors :class:`~marketing_shorts_agent.content.StockInfo`.
    """

    ticker: str
    company_name: str
    sector: str
    figures: list[FigureItem]


class PublishResultResponse(BaseModel):
    """Serialisable form of :class:`~marketing_shorts_agent.publisher.PublishResult`."""

    video_id: str
    url: str
    dry_run: bool


class PipelineResultResponse(BaseModel):
    """Serialisable form of :class:`~marketing_shorts_agent.pipeline.PipelineResult`."""

    success: bool
    ticker: str
    version_id: str
    errors: list[str]
    render_job_id: str
    render_job_state: str
    video_url: str | None
    publish_result: PublishResultResponse | None


def _to_response(result: PipelineResult) -> PipelineResultResponse:
    """Convert a :class:`PipelineResult` dataclass to a JSON-serialisable response."""
    pub: PublishResultResponse | None = None
    if result.publish_result is not None:
        pub = PublishResultResponse(
            video_id=result.publish_result.video_id,
            url=result.publish_result.url,
            dry_run=result.publish_result.dry_run,
        )
    return PipelineResultResponse(
        success=result.success,
        ticker=result.ticker,
        version_id=result.version_id,
        errors=result.errors,
        render_job_id=result.render_job.render_id,
        render_job_state=result.render_job.state.value,
        video_url=result.render_job.video_url,
        publish_result=pub,
    )


# ── Global orchestrator ───────────────────────────────────────────────────────

_orchestrator: PipelineOrchestrator | None = None


def _build_orchestrator() -> PipelineOrchestrator:
    """Construct the :class:`PipelineOrchestrator` from environment variables.

    When ``RENDERER_URL`` is empty the bundled renderer-stub is started
    in-process on a free port and its URL is forwarded to :class:`PipelineConfig`.
    Content- and storyboard-stub startup is delegated to
    :class:`PipelineOrchestrator` itself (existing behaviour).

    When ``AGENTOPS_BASE_URL`` is empty the default stub implementations are
    used for the evaluator, analytics, and version-register steps — no network
    calls are made (matching the existing ``PipelineConfig`` defaults).
    """
    renderer_url: str = os.environ.get("RENDERER_URL", "").strip()
    content_url: str = os.environ.get("CONTENT_URL", "").strip()
    storyboard_url: str = os.environ.get("STORYBOARD_URL", "").strip()
    dry_run: bool = os.environ.get("DRY_RUN", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    )

    if not renderer_url:
        # Import helpers from orchestrator to reuse port-allocation + stub-startup logic.
        from .pipeline.orchestrator import _allocate_port, _start_stub_server  # noqa: PLC0415
        from renderer_stub.app import app as _renderer_stub_app  # noqa: PLC0415

        port = _allocate_port(18080)
        _start_stub_server(_renderer_stub_app, "127.0.0.1", port)
        renderer_url = f"http://127.0.0.1:{port}/v1"
        logger.info("Bundled renderer-stub started", extra={"url": renderer_url})

    agentops_base_url: str = os.environ.get("AGENTOPS_BASE_URL", "").strip()
    agentops_agent_id: str = os.environ.get("AGENTOPS_AGENT_ID", "marketing-shorts-agent").strip()
    agentops_api_key: str = os.environ.get("AGENTOPS_API_KEY", "").strip()

    version_register = None
    analytics = None

    if agentops_base_url:
        from .analytics.client import AgentOpsAnalyticsClient  # noqa: PLC0415
        from .version_register.client import AgentOpsVersionRegisterClient  # noqa: PLC0415

        bearer_token: str | None = agentops_api_key if agentops_api_key else None

        version_register = AgentOpsVersionRegisterClient(
            base_url=agentops_base_url,
            bearer_token=bearer_token,
            dry_run=False,
        )
        analytics = AgentOpsAnalyticsClient(
            base_url=agentops_base_url,
            bearer_token=bearer_token,
            dry_run=False,
        )
        logger.info(
            "AgentOps live clients configured",
            extra={
                "agentops_base_url": agentops_base_url,
                "agent_id": agentops_agent_id,
                "auth": "bearer" if bearer_token else "none",
            },
        )
    else:
        logger.info(
            "AGENTOPS_BASE_URL not set; stub implementations used for "
            "version-register and analytics"
        )

    config = PipelineConfig(
        renderer_base_url=renderer_url,
        content_url=content_url,
        storyboard_url=storyboard_url,
        dry_run=dry_run,
        agent_id=agentops_agent_id,
        version_register=version_register,
        analytics=analytics,
    )
    logger.info(
        "Building PipelineOrchestrator",
        extra={
            "renderer_base_url": renderer_url,
            "content_url": content_url or "(bundled stub)",
            "storyboard_url": storyboard_url or "(bundled stub)",
            "dry_run": dry_run,
        },
    )
    return PipelineOrchestrator(config)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: ARG001
    """Start the pipeline orchestrator (and any bundled stubs) on app startup."""
    global _orchestrator  # noqa: PLW0603

    logger.info("marketing-shorts-agent starting up")
    _orchestrator = _build_orchestrator()
    logger.info(
        "Pipeline orchestrator ready",
        extra={"dry_run": _orchestrator._config.dry_run},
    )

    yield

    logger.info("marketing-shorts-agent shutting down")


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(
    title="marketing-shorts-agent",
    version="0.1.0",
    description=(
        "Autonomous AI agent that turns Japanese-stock financial data into "
        "YouTube Shorts — from script generation through render — in a single pipeline call."
    ),
    lifespan=_lifespan,
)

# ── Endpoints ─────────────────────────────────────────────────────────────────

_PIPELINE_STAGES = [
    "Content generation (script) — via external content service or bundled stub",
    "YMYL guard (script) — disclaimer &amp; recommendation check",
    "Evaluator hook — trajectory / drift scoring",
    "Storyboard generation — via external storyboard service or bundled stub",
    "YMYL guard (storyboard)",
    "Renderer submit &amp; wait — via external renderer or bundled renderer-stub",
    "Publisher — YouTube Shorts upload (dry-run by default)",
    "Version register",
    "Analytics push",
]

_LANDING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>marketing-shorts-agent</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      max-width: 760px;
      margin: 48px auto;
      padding: 0 24px;
      color: #1a1a1a;
      line-height: 1.6;
    }}
    h1 {{ font-size: 1.75rem; margin-bottom: 0.25rem; }}
    h2 {{ font-size: 1.15rem; margin-top: 2rem; color: #333; }}
    .tagline {{ color: #555; margin-top: 0.25rem; font-size: 1.05rem; }}
    ol li {{ margin-bottom: 0.3rem; }}
    a {{ color: #0057b8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      background: #f0f0f0;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.9em;
    }}
    .links li {{ list-style: none; margin-bottom: 0.4rem; }}
    .links {{ padding-left: 0; }}
  </style>
</head>
<body>
  <h1>marketing-shorts-agent</h1>
  <p class="tagline">
    An autonomous AI agent that turns Japanese-stock financial data into YouTube Shorts —
    from script generation through render — in a single pipeline call.
  </p>

  <h2>Pipeline stages</h2>
  <ol>
{stages}
  </ol>

  <h2>API</h2>
  <ul class="links">
    <li><a href="/docs">Interactive API docs (Swagger UI)</a></li>
    <li><a href="/redoc">ReDoc API reference</a></li>
    <li><a href="/healthz">Health check — <code>GET /healthz</code></a></li>
    <li>
      Run pipeline — <code>POST /pipeline/run</code>
      with a JSON body containing <code>ticker</code>, <code>company_name</code>,
      <code>sector</code>, and <code>figures</code>.
    </li>
  </ul>
</body>
</html>
""".format(
    stages="\n".join(f"    <li>{stage}</li>" for stage in _PIPELINE_STAGES)
)


@app.get("/healthz", summary="Health check")
def health() -> dict[str, str]:
    """Return ``{"status": "ok"}`` when the service is running."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing() -> str:
    """HTML landing page with agent description and API links."""
    return _LANDING_HTML


@app.post(
    "/pipeline/run",
    response_model=PipelineResultResponse,
    summary="Run the Shorts generation pipeline",
)
def pipeline_run(request: StockInfoRequest) -> PipelineResultResponse:
    """Execute the full Shorts generation pipeline for a single stock.

    Accepts stock financial data and runs the end-to-end pipeline
    (content → YMYL → storyboard → render → publish).  Returns the pipeline
    result including render-job state and publish result.

    Runs synchronously; expect a few seconds in bundled-stub mode.
    Set ``DRY_RUN=false`` and provide YouTube credentials to enable real upload.
    """
    if _orchestrator is None:  # pragma: no cover — lifespan guarantees initialisation
        raise RuntimeError("Pipeline orchestrator is not initialised")

    stock_info = StockInfo(
        ticker=request.ticker,
        company_name=request.company_name,
        sector=request.sector,
        figures=list(request.figures),
    )
    result = _orchestrator.run(stock_info)
    return _to_response(result)
