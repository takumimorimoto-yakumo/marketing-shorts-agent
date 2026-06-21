"""Pipeline orchestrator skeleton (ADK-based).

This module wires all pipeline components together.  The orchestrator is the
single entry point for the end-to-end Shorts generation pipeline.

ADK integration note: in production this class is wrapped as an ADK Agent,
with each stage exposed as a tool/callback.  For local dev and tests, it runs
synchronously without ADK.

Pipeline stages:
  1. Content generation (script)
  2. YMYL guard (script)
  3. Evaluator hook
  4. Storyboard generation
  5. YMYL guard (storyboard)
  6. Renderer submit + wait
  7. Publisher (dry-run by default)
  8. Analytics push
  9. Version register
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..analytics import AnalyticsInterface, AnalyticsStub
from ..content import ContentGeneratorInterface, ExampleContentGenerator, StockInfo
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
from ..version_register import VersionRecord, VersionRegisterInterface, VersionRegisterStub

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Runtime configuration for the pipeline orchestrator."""

    renderer_base_url: str
    """Base URL of the renderer service (e.g. 'http://localhost:8080')."""

    dry_run: bool = True
    """When True, the publisher does not actually upload to YouTube."""

    content_generator: ContentGeneratorInterface | None = None
    """Override the content generator.  Defaults to ExampleContentGenerator."""

    storyboard_generator: StoryboardGeneratorInterface | None = None
    """Override the storyboard generator.  Defaults to ExampleStoryboardGenerator."""

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


class PipelineOrchestrator:
    """End-to-end Shorts pipeline orchestrator.

    Usage (with bundled stubs for E2E tests)::

        config = PipelineConfig(renderer_base_url="http://localhost:8080")
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(StockInfo(ticker="7203", company_name="Toyota", ...))
        assert result.success
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config
        self._content = config.content_generator or ExampleContentGenerator()
        self._storyboard_gen = config.storyboard_generator or ExampleStoryboardGenerator()
        self._evaluator = config.evaluator or EvaluatorStub()
        self._publisher = config.publisher or DryRunPublisher()
        self._analytics = config.analytics or AnalyticsStub()
        self._version_register = config.version_register or VersionRegisterStub()

    def run(self, stock_info: StockInfo) -> PipelineResult:
        """Execute the full pipeline for a single stock.  Synchronous."""
        logger.info("Pipeline start", extra={"ticker": stock_info.ticker})

        # 1. Script generation
        script = self._content.generate(stock_info)
        logger.info("Script generated", extra={"ticker": script.ticker, "segments": len(script.segments)})

        # 2. YMYL guard (script)
        enforce_script_ymyl(script)
        logger.info("Script YMYL guard passed")

        # 3. Evaluator
        eval_result = self._evaluator.evaluate(script)
        if not eval_result.passed:
            raise ValueError(f"Evaluator rejected script: {eval_result.violations}")
        logger.info("Evaluator passed", extra={"score": eval_result.score})

        # 4. Storyboard generation
        storyboard = self._storyboard_gen.generate(script)
        logger.info("Storyboard generated", extra={"scenes": len(storyboard.scenes)})

        # 5. YMYL guard (storyboard)
        enforce_storyboard_ymyl(storyboard)
        logger.info("Storyboard YMYL guard passed")

        # 6. Renderer
        render_job = self._render(storyboard)
        logger.info("Render complete", extra={"render_id": render_job.render_id, "state": render_job.state})

        # 7. Publisher
        video_path = render_job.video_url or ""
        publish_result = self._publisher.publish(
            video_path, storyboard, dry_run=self._config.dry_run
        )
        logger.info("Publish complete", extra={"video_id": publish_result.video_id})

        # 8. Analytics (best-effort — don't fail the pipeline)
        try:
            metrics = self._analytics.pull(publish_result.video_id)
            self._analytics.push(metrics, self._config.agent_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analytics step failed (non-fatal): %s", exc)

        # 9. Version register
        version_id = self._version_register.register(
            VersionRecord(
                agent_id=self._config.agent_id,
                version=self._config.agent_version,
                content_generator_class=type(self._content).__qualname__,
                metadata={"ticker": stock_info.ticker, "video_id": publish_result.video_id},
            )
        )

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
