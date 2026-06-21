"""E2E pipeline test — script → storyboard → (stub) render.

This test starts the renderer-stub in-process (no network required) and runs
the full pipeline from StockInfo to a completed RenderJob.
"""

from __future__ import annotations

import threading

import pytest
import uvicorn

from marketing_shorts_agent.content import ExampleContentGenerator, StockInfo
from marketing_shorts_agent.models import FigureItem, RenderJobState
from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator


class _ThreadedServer:
    """Run renderer-stub in a background thread for E2E tests."""

    def __init__(self, host: str = "127.0.0.1", port: int = 18080) -> None:
        from renderer_stub.app import app

        self.host = host
        self.port = port
        self._config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(self._config)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        # Wait until the server is ready
        import time
        import httpx

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                httpx.get(f"http://{self.host}:{self.port}/v1/renders/probe", timeout=1)
            except Exception:
                pass
            # Any response (even 404) means the server is up
            try:
                r = httpx.get(f"http://{self.host}:{self.port}/v1/renders/probe", timeout=1)
                break
            except Exception:
                time.sleep(0.1)

    def stop(self) -> None:
        self._server.should_exit = True


@pytest.fixture(scope="module")
def renderer_stub_url() -> str:
    """Start renderer-stub server once per module and return its base URL.

    The renderer-stub mounts all routes under /v1/ (e.g. POST /v1/renders).
    The RendererClient appends /renders to the base_url, so base_url must
    include the /v1 prefix.
    """
    server = _ThreadedServer(port=18080)
    server.start()
    yield "http://127.0.0.1:18080/v1"
    server.stop()


class TestE2EPipeline:
    def _stock_info(self) -> StockInfo:
        return StockInfo(
            ticker="7203",
            company_name="サンプル株式会社",
            sector="製造業",
            figures=[
                FigureItem(label="PER", value="12.3x"),
                FigureItem(label="PBR", value="1.5x"),
                FigureItem(label="売上高", value="¥3,000億"),
            ],
        )

    def test_full_pipeline_succeeds(self, renderer_stub_url: str):
        """Full pipeline: StockInfo → script → storyboard → render → publish (dry-run)."""
        config = PipelineConfig(
            renderer_base_url=renderer_stub_url,
            dry_run=True,
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.success, f"Pipeline errors: {result.errors}"
        assert result.ticker == "7203"
        assert result.render_job.state == RenderJobState.DONE
        assert result.publish_result is not None
        assert result.publish_result.dry_run is True
        assert result.version_id.startswith("stub-ver-")

    def test_script_has_disclaimer(self, renderer_stub_url: str):
        """Generated script must contain a disclaimer segment."""
        gen = ExampleContentGenerator()
        script = gen.generate(self._stock_info())
        from marketing_shorts_agent.models import ScriptShotType

        types = [s.type for s in script.segments]
        assert ScriptShotType.DISCLAIMER in types

    def test_storyboard_has_disclaimer_shot(self, renderer_stub_url: str):
        """Generated storyboard must contain a disclaimer shot."""
        from marketing_shorts_agent.storyboard import ExampleStoryboardGenerator

        gen_content = ExampleContentGenerator()
        gen_story = ExampleStoryboardGenerator()
        script = gen_content.generate(self._stock_info())
        storyboard = gen_story.generate(script)
        assert storyboard.has_disclaimer()

    def test_version_id_registered_before_analytics(self, renderer_stub_url: str):
        """Regression: version_id must be a real version-register id, not agent_id fallback.

        The pipeline must register a version before calling analytics.push() so
        that MetricIngest.versionId carries the actual version id.  We verify
        that result.version_id is not equal to the agent_id config value, which
        was the incorrect fallback before the ordering fix.
        """
        config = PipelineConfig(
            renderer_base_url=renderer_stub_url,
            dry_run=True,
            agent_id="marketing-shorts-agent",
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.success, f"Pipeline errors: {result.errors}"
        # version_id must come from the version register stub (prefix "stub-ver-")
        assert result.version_id != "marketing-shorts-agent", (
            "version_id must not fall back to agent_id; "
            "version register must run before analytics"
        )
        assert result.version_id, "version_id must not be empty"
