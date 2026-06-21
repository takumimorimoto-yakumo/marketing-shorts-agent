"""Pipeline orchestrator skeleton (ADK-based).

This module wires all pipeline components together.  The orchestrator is the
single entry point for the end-to-end Shorts generation pipeline.

ADK integration note: in production this class is wrapped as an ADK Agent,
with each stage exposed as a tool/callback.  For local dev and tests, it runs
synchronously without ADK.

Pipeline stages:
  1. Content generation (script) — via HTTP content service or bundled stub
  2. YMYL guard (script)
  3. Evaluator hook
  4. Storyboard generation — via HTTP storyboard service or bundled stub
  5. YMYL guard (storyboard)
  6. Renderer submit + wait — via HTTP renderer service or bundled stub
  7. Publisher (dry-run by default)
  8. Version register  ← must precede analytics so versionId is available
  9. Analytics push    ← receives the real versionId from step 8

Bring-your-own services:
  Set ``content_url``, ``storyboard_url``, or ``renderer_base_url`` in
  PipelineConfig to point any stage at an external HTTP service.  When a URL
  is empty the corresponding bundled stub is started in-process.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from ..analytics import AnalyticsInterface, AnalyticsStub
from ..content import ContentGeneratorInterface, ExampleContentGenerator, StockInfo
from ..content.client import ContentServiceClient
from ..evaluator import EvaluatorInterface, EvaluatorStub
from ..guards import (
    DisclaimerMissingError,
    RecommendationDetectedError,
    enforce_script_ymyl,
    enforce_storyboard_ymyl,
)
from ..models import FigureItem, RenderJob, Script, Storyboard
from ..publisher import DryRunPublisher, PublishResult, PublisherInterface
from ..renderer import RendererClient, RendererClientError
from ..storyboard import ExampleStoryboardGenerator, StoryboardGeneratorInterface
from ..storyboard.client import StoryboardServiceClient
from ..version_register import VersionRecord, VersionRegisterInterface, VersionRegisterStub

logger = logging.getLogger(__name__)

# ── Bundled-stub lifecycle helpers ────────────────────────────────────────────


def _start_stub_server(app: object, host: str, port: int) -> threading.Thread:
    """Start a FastAPI stub in a daemon thread.  Returns the thread."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _run() -> None:
        server.run()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # Wait until the stub is accepting connections
    import time

    import httpx

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://{host}:{port}/", timeout=0.5)
            break
        except Exception:
            time.sleep(0.05)
    return thread


def _allocate_port(preferred: int) -> int:
    """Return *preferred* if free; otherwise let the OS pick a free port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


# ── PipelineConfig ─────────────────────────────────────────────────────────────


@dataclass
class PipelineConfig:
    """Runtime configuration for the pipeline orchestrator."""

    renderer_base_url: str
    """Base URL of the renderer service (e.g. 'http://localhost:8080/v1').
    Required; use the bundled stub's URL when running locally."""

    dry_run: bool = True
    """When True, the publisher does not actually upload to YouTube."""

    content_url: str = ""
    """Base URL of the content service (e.g. 'http://localhost:9081/v1').
    Empty → start bundled content-stub in-process and use it."""

    storyboard_url: str = ""
    """Base URL of the storyboard service (e.g. 'http://localhost:9082/v1').
    Empty → start bundled storyboard-stub in-process and use it."""

    content_generator: ContentGeneratorInterface | None = None
    """Override the content generator directly (bypasses content_url).
    Kept for backward compatibility and direct in-process testing."""

    storyboard_generator: StoryboardGeneratorInterface | None = None
    """Override the storyboard generator directly (bypasses storyboard_url).
    Kept for backward compatibility and direct in-process testing."""

    evaluator: EvaluatorInterface | None = None
    """Override the evaluator.  Defaults to EvaluatorStub."""

    publisher: PublisherInterface | None = None
    """Override the publisher.  Defaults to DryRunPublisher."""

    analytics: AnalyticsInterface | None = None
    """Override the analytics connector.  Defaults to AnalyticsStub."""

    version_register: VersionRegisterInterface | None = None
    """Override the version register.  Defaults to VersionRegisterStub."""

    agent_version: str = "0.1.0"
    agent_id: str = "marketing-shorts-agent"


# ── PipelineResult ─────────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    """Result of one pipeline run."""

    ticker: str
    script: Script
    storyboard: Storyboard
    render_job: RenderJob
    publish_result: PublishResult | None = None
    version_id: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


# ── PipelineOrchestrator ───────────────────────────────────────────────────────


class PipelineOrchestrator:
    """End-to-end Shorts pipeline orchestrator.

    All three generators (content, storyboard, renderer) are external HTTP
    services.  When a URL is not configured the corresponding bundled stub is
    started in-process so the pipeline runs without any external dependency.

    Usage (all bundled stubs, E2E tests)::

        config = PipelineConfig(renderer_base_url="http://localhost:8080/v1")
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(StockInfo(ticker="7203", ...))
        assert result.success

    Usage (external content service)::

        config = PipelineConfig(
            renderer_base_url="http://localhost:8080/v1",
            content_url="https://content.run.app/v1",
        )
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config
        self._evaluator = config.evaluator or EvaluatorStub()
        self._publisher = config.publisher or DryRunPublisher()
        self._analytics = config.analytics or AnalyticsStub()
        self._version_register = config.version_register or VersionRegisterStub()

        # Content generator: explicit > URL > bundled stub (in-process)
        if config.content_generator is not None:
            self._content: ContentGeneratorInterface = config.content_generator
        elif config.content_url:
            self._content = ContentServiceClient(base_url=config.content_url)
        else:
            # Start bundled content-stub in-process
            self._content = self._start_bundled_content_stub()

        # Storyboard generator: explicit > URL > bundled stub (in-process)
        if config.storyboard_generator is not None:
            self._storyboard_gen: StoryboardGeneratorInterface = config.storyboard_generator
        elif config.storyboard_url:
            self._storyboard_gen = StoryboardServiceClient(base_url=config.storyboard_url)
        else:
            # Start bundled storyboard-stub in-process
            self._storyboard_gen = self._start_bundled_storyboard_stub()

    # ── Bundled-stub launchers ────────────────────────────────────────────────

    def _start_bundled_content_stub(self) -> ContentServiceClient:
        """Start the bundled content-stub server and return a client for it."""
        from content_stub.app import app

        port = _allocate_port(19081)
        _start_stub_server(app, "127.0.0.1", port)
        base_url = f"http://127.0.0.1:{port}/v1"
        logger.info("Bundled content-stub started", extra={"url": base_url})
        return ContentServiceClient(base_url=base_url)

    def _start_bundled_storyboard_stub(self) -> StoryboardServiceClient:
        """Start the bundled storyboard-stub server and return a client for it."""
        from storyboard_stub.app import app

        port = _allocate_port(19082)
        _start_stub_server(app, "127.0.0.1", port)
        base_url = f"http://127.0.0.1:{port}/v1"
        logger.info("Bundled storyboard-stub started", extra={"url": base_url})
        return StoryboardServiceClient(base_url=base_url)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, stock_info: StockInfo) -> PipelineResult:
        """Execute the full pipeline for a single stock.  Synchronous."""
        logger.info("Pipeline start", extra={"ticker": stock_info.ticker})

        # 1. Script generation (HTTP content service or bundled stub)
        script = self._content.generate(stock_info)
        logger.info(
            "Script generated",
            extra={"ticker": script.ticker, "segments": len(script.segments)},
        )

        # 2. YMYL guard (script) — enforced by this agent regardless of source
        enforce_script_ymyl(script)
        logger.info("Script YMYL guard passed")

        # 3. Evaluator
        eval_result = self._evaluator.evaluate(script)
        if not eval_result.passed:
            raise ValueError(f"Evaluator rejected script: {eval_result.violations}")
        logger.info("Evaluator passed", extra={"score": eval_result.score})

        # 4. Storyboard generation (HTTP storyboard service or bundled stub)
        storyboard = self._storyboard_gen.generate(script)
        logger.info("Storyboard generated", extra={"scenes": len(storyboard.scenes)})

        # 5. YMYL guard (storyboard) — enforced by this agent regardless of source
        enforce_storyboard_ymyl(storyboard)
        logger.info("Storyboard YMYL guard passed")

        # 6. Renderer (HTTP renderer service)
        render_job = self._render(storyboard)
        logger.info(
            "Render complete",
            extra={"render_id": render_job.render_id, "state": render_job.state},
        )

        # 7. Publisher
        video_path = render_job.video_url or ""
        publish_result = self._publisher.publish(
            video_path, storyboard, dry_run=self._config.dry_run
        )
        logger.info("Publish complete", extra={"video_id": publish_result.video_id})

        # 8. Version register — must run before analytics so the real versionId
        #    is available to embed in MetricIngest.versionId (avoids agent_id fallback).
        version_id = self._version_register.register(
            VersionRecord(
                agent_id=self._config.agent_id,
                version=self._config.agent_version,
                content_generator_class=type(self._content).__qualname__,
                metadata={"ticker": stock_info.ticker, "video_id": publish_result.video_id},
            )
        )
        logger.info("Version registered", extra={"version_id": version_id})

        # 9. Analytics (best-effort — don't fail the pipeline).
        #    Pass version_id via metrics.extra so _build_payload can embed the
        #    real versionId (registered in step 8) in MetricIngest.
        try:
            metrics = self._analytics.pull(publish_result.video_id)
            metrics.extra["version_id"] = version_id
            self._analytics.push(metrics, self._config.agent_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analytics step failed (non-fatal): %s", exc)

        return PipelineResult(
            ticker=stock_info.ticker,
            script=script,
            storyboard=storyboard,
            render_job=render_job,
            publish_result=publish_result,
            version_id=version_id,
        )

    def _render(self, storyboard: Storyboard) -> RenderJob:
        with RendererClient(base_url=self._config.renderer_base_url) as client:
            job = client.submit(storyboard)
            return client.wait(job.render_id, poll_interval_sec=0.1)
