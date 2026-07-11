"""Tests for the video_qa module and its integration with the pipeline.

Unit tests:
  - QaResult.to_metrics() — correct metric names and values
  - VideoQAStub — always returns pass with expected structure
  - VideoQAClient deterministic helpers — ffprobe parsing, luminance checks

Stub E2E tests (via PipelineOrchestrator):
  - POST /pipeline/run returns qa_verdict in the response (stub mode)
  - QA pass → publish_result is present
  - QA fail (injected failing QA) → publish is skipped, errors non-empty, qa_verdict is fail
  - QA error (injected error QA) → publish is skipped, errors non-empty, qa_verdict is error

All tests run without network, without ffprobe/ffmpeg, without Gemini credentials.
"""

from __future__ import annotations

import pytest

from marketing_shorts_agent.video_qa import (
    DeterministicCheckResult,
    QaResult,
    QaVerdict,
    VideoQAInterface,
    VideoQAStub,
    VisualCheckResult,
)
from marketing_shorts_agent.video_qa.client import _parse_visual_response, _resolve_local_path


# ── QaResult.to_metrics() ─────────────────────────────────────────────────────


class TestQaResultToMetrics:
    def test_pass_verdict_gives_1(self):
        result = QaResult(verdict=QaVerdict.PASS)
        metrics = result.to_metrics()
        assert metrics["video_qa_pass"] == 1.0

    def test_fail_verdict_gives_0(self):
        result = QaResult(verdict=QaVerdict.FAIL)
        metrics = result.to_metrics()
        assert metrics["video_qa_pass"] == 0.0

    def test_error_verdict_gives_0(self):
        result = QaResult(verdict=QaVerdict.ERROR, error="infrastructure failure")
        metrics = result.to_metrics()
        assert metrics["video_qa_pass"] == 0.0

    def test_deterministic_check_included(self):
        result = QaResult(
            verdict=QaVerdict.PASS,
            deterministic_checks=[
                DeterministicCheckResult(name="video_stream_present", passed=True),
                DeterministicCheckResult(name="duration_in_range", passed=False),
            ],
        )
        metrics = result.to_metrics()
        assert metrics["video_qa_video_stream_present"] == 1.0
        assert metrics["video_qa_duration_in_range"] == 0.0

    def test_visual_check_included(self):
        result = QaResult(
            verdict=QaVerdict.PASS,
            visual_check=VisualCheckResult(
                passed=True,
                rubric_scores={"text_legibility": 0.9, "layout": 0.8, "readability": 0.7},
            ),
        )
        metrics = result.to_metrics()
        assert metrics["video_qa_visual_pass"] == 1.0
        assert metrics["video_qa_visual_text_legibility"] == pytest.approx(0.9)
        assert metrics["video_qa_visual_layout"] == pytest.approx(0.8)
        assert metrics["video_qa_visual_readability"] == pytest.approx(0.7)

    def test_no_visual_check_no_visual_metrics(self):
        result = QaResult(verdict=QaVerdict.PASS)
        metrics = result.to_metrics()
        assert "video_qa_visual_pass" not in metrics

    def test_check_names_with_hyphens_normalised(self):
        result = QaResult(
            verdict=QaVerdict.PASS,
            deterministic_checks=[
                DeterministicCheckResult(name="no-black-frames", passed=True),
            ],
        )
        metrics = result.to_metrics()
        assert "video_qa_no_black_frames" in metrics


# ── VideoQAStub ───────────────────────────────────────────────────────────────


class TestVideoQAStub:
    def test_stub_returns_pass(self):
        stub = VideoQAStub()
        result = stub.run("stub://no-ffmpeg/test.mp4")
        assert result.verdict == QaVerdict.PASS
        assert result.passed is True

    def test_stub_has_all_deterministic_checks(self):
        stub = VideoQAStub()
        result = stub.run("stub://no-ffmpeg/test.mp4")
        check_names = {c.name for c in result.deterministic_checks}
        assert "video_stream_present" in check_names
        assert "duration_in_range" in check_names
        assert "no_black_frames" in check_names
        assert "no_white_frames" in check_names

    def test_stub_all_deterministic_checks_pass(self):
        stub = VideoQAStub()
        result = stub.run("stub://no-ffmpeg/test.mp4")
        for check in result.deterministic_checks:
            assert check.passed, f"Expected {check.name} to pass in stub"

    def test_stub_has_visual_check(self):
        stub = VideoQAStub()
        result = stub.run("stub://no-ffmpeg/test.mp4")
        assert result.visual_check is not None
        assert result.visual_check.passed is True

    def test_stub_visual_rubric_scores_present(self):
        stub = VideoQAStub()
        result = stub.run("stub://no-ffmpeg/test.mp4")
        assert result.visual_check is not None
        assert "text_legibility" in result.visual_check.rubric_scores
        assert "layout" in result.visual_check.rubric_scores
        assert "readability" in result.visual_check.rubric_scores

    def test_stub_to_metrics_complete(self):
        stub = VideoQAStub()
        result = stub.run("stub://no-ffmpeg/test.mp4")
        metrics = result.to_metrics()
        assert metrics["video_qa_pass"] == 1.0
        assert "video_qa_visual_pass" in metrics

    def test_stub_ignores_expected_duration(self):
        stub = VideoQAStub()
        result = stub.run("stub://no-ffmpeg/test.mp4", expected_duration_sec=30.0)
        assert result.passed is True

    def test_stub_file_url(self):
        stub = VideoQAStub()
        result = stub.run("file:///tmp/nonexistent.mp4")
        # Stub always passes regardless of path
        assert result.passed is True


# ── _resolve_local_path (VideoQAClient helper) ────────────────────────────────


class TestResolveLocalPath:
    def test_stub_url_returns_none(self):
        assert _resolve_local_path("stub://no-ffmpeg/render123.mp4") is None

    def test_file_url_nonexistent_returns_none(self):
        assert _resolve_local_path("file:///nonexistent/path/video.mp4") is None

    def test_bare_nonexistent_path_returns_none(self):
        assert _resolve_local_path("/no/such/file.mp4") is None

    def test_file_url_existing_file(self, tmp_path):
        p = tmp_path / "test.mp4"
        p.write_bytes(b"fake")
        result = _resolve_local_path(f"file://{p}")
        assert result == str(p)

    def test_bare_existing_path(self, tmp_path):
        p = tmp_path / "test.mp4"
        p.write_bytes(b"fake")
        result = _resolve_local_path(str(p))
        assert result == str(p)


# ── _parse_visual_response ────────────────────────────────────────────────────


class TestParseVisualResponse:
    def test_valid_json_pass(self):
        raw = '{"text_legibility": 0.9, "layout": 0.8, "readability": 0.9, "pass": true, "reason": "Looks good"}'
        result = _parse_visual_response(raw)
        assert result.passed is True
        assert result.rubric_scores["text_legibility"] == pytest.approx(0.9)
        assert result.reason == "Looks good"

    def test_valid_json_fail(self):
        raw = '{"text_legibility": 0.2, "layout": 0.1, "readability": 0.3, "pass": false, "reason": "Text cut off"}'
        result = _parse_visual_response(raw)
        assert result.passed is False
        assert result.reason == "Text cut off"

    def test_markdown_fenced_json(self):
        raw = '```json\n{"text_legibility": 1.0, "layout": 1.0, "readability": 1.0, "pass": true, "reason": "ok"}\n```'
        result = _parse_visual_response(raw)
        assert result.passed is True

    def test_invalid_json_returns_fail(self):
        result = _parse_visual_response("this is not json")
        assert result.passed is False
        assert "parse error" in result.reason.lower()

    def test_empty_string_returns_fail(self):
        result = _parse_visual_response("")
        assert result.passed is False

    def test_partial_rubric_still_works(self):
        raw = '{"text_legibility": 0.8, "pass": true, "reason": "partial"}'
        result = _parse_visual_response(raw)
        assert result.passed is True
        assert "text_legibility" in result.rubric_scores


# ── Failing QA stub (for pipeline gate tests) ─────────────────────────────────


class _FailingQAStub(VideoQAInterface):
    """QA stub that always fails — used to verify publish is skipped."""

    def run(self, video_path: str, expected_duration_sec: float | None = None) -> QaResult:
        return QaResult(
            verdict=QaVerdict.FAIL,
            deterministic_checks=[
                DeterministicCheckResult(
                    name="video_stream_present",
                    passed=False,
                    detail="injected failure for test",
                )
            ],
        )


class _ErrorQAStub(VideoQAInterface):
    """QA stub that raises — verify fail-closed behaviour."""

    def run(self, video_path: str, expected_duration_sec: float | None = None) -> QaResult:
        raise RuntimeError("Simulated QA infrastructure error")


# ── Pipeline gate integration (orchestrator-level) ────────────────────────────


@pytest.fixture(scope="module")
def renderer_stub_url_qa():
    """Start renderer-stub once per module for QA integration tests."""
    import threading
    import time

    import httpx
    import uvicorn

    from renderer_stub.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=18085, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            httpx.get("http://127.0.0.1:18085/v1/renders/probe", timeout=0.5)
        except Exception:
            pass
        try:
            r = httpx.get("http://127.0.0.1:18085/v1/renders/probe", timeout=0.5)
            break
        except Exception:
            time.sleep(0.05)

    yield "http://127.0.0.1:18085/v1"
    server.should_exit = True


class TestPipelineQAGate:
    """Integration tests for the video_qa gate in PipelineOrchestrator."""

    def _stock_info(self):
        from marketing_shorts_agent.content import StockInfo
        from marketing_shorts_agent.models import FigureItem

        return StockInfo(
            ticker="7203",
            company_name="テスト株式会社",
            sector="製造業",
            figures=[FigureItem(label="PER", value="12.3x")],
        )

    def test_qa_pass_pipeline_succeeds(self, renderer_stub_url_qa: str):
        """Default stub QA (pass) → pipeline succeeds and publish_result is present."""
        from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator

        config = PipelineConfig(
            renderer_base_url=renderer_stub_url_qa,
            dry_run=True,
            video_qa=VideoQAStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.success, f"Pipeline errors: {result.errors}"
        assert result.publish_result is not None, "publish_result must be present when QA passes"

    def test_qa_pass_verdict_in_result(self, renderer_stub_url_qa: str):
        """When QA passes, qa_verdict.verdict == 'pass'."""
        from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator

        config = PipelineConfig(
            renderer_base_url=renderer_stub_url_qa,
            dry_run=True,
            video_qa=VideoQAStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.qa_verdict is not None
        assert result.qa_verdict.verdict == "pass"

    def test_qa_fail_publish_skipped(self, renderer_stub_url_qa: str):
        """Injected QA fail → publish_result is None and pipeline has errors."""
        from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator

        config = PipelineConfig(
            renderer_base_url=renderer_stub_url_qa,
            dry_run=True,
            video_qa=_FailingQAStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert not result.success, "Pipeline should report failure when QA fails"
        assert result.publish_result is None, "publish_result must be None when QA fails"
        assert len(result.errors) > 0, "errors must be non-empty when QA fails"

    def test_qa_fail_verdict_in_result(self, renderer_stub_url_qa: str):
        """Injected QA fail → qa_verdict.verdict == 'fail'."""
        from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator

        config = PipelineConfig(
            renderer_base_url=renderer_stub_url_qa,
            dry_run=True,
            video_qa=_FailingQAStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.qa_verdict is not None
        assert result.qa_verdict.verdict == "fail"

    def test_qa_error_fail_closed(self, renderer_stub_url_qa: str):
        """Injected QA exception → fail-closed: publish skipped, errors recorded."""
        from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator

        config = PipelineConfig(
            renderer_base_url=renderer_stub_url_qa,
            dry_run=True,
            video_qa=_ErrorQAStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert not result.success
        assert result.publish_result is None
        assert len(result.errors) > 0

    def test_qa_error_verdict_in_result(self, renderer_stub_url_qa: str):
        """Injected QA exception → qa_verdict.verdict == 'error'."""
        from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator

        config = PipelineConfig(
            renderer_base_url=renderer_stub_url_qa,
            dry_run=True,
            video_qa=_ErrorQAStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.qa_verdict is not None
        assert result.qa_verdict.verdict == "error"

    def test_qa_metrics_in_analytics_stub(self, renderer_stub_url_qa: str):
        """QA metrics are passed to analytics.push() via VideoMetrics.extra."""
        from unittest.mock import MagicMock

        from marketing_shorts_agent.analytics import AnalyticsStub
        from marketing_shorts_agent.analytics.interface import VideoMetrics
        from marketing_shorts_agent.pipeline import PipelineConfig, PipelineOrchestrator

        captured: list[VideoMetrics] = []

        class _CapturingStub(AnalyticsStub):
            def push(self, metrics: VideoMetrics, agent_id: str) -> None:
                captured.append(metrics)

        config = PipelineConfig(
            renderer_base_url=renderer_stub_url_qa,
            dry_run=True,
            video_qa=VideoQAStub(),
            analytics=_CapturingStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.success
        assert len(captured) == 1, "analytics.push must be called once"
        pushed_metrics = captured[0]
        assert "video_qa_pass" in pushed_metrics.extra, (
            "QA metrics must be present in analytics push extra"
        )
        assert pushed_metrics.extra["video_qa_pass"] == 1.0


# ── FastAPI E2E — qa_verdict in HTTP response ─────────────────────────────────


class TestAPIQaVerdict:
    """Verify POST /pipeline/run includes qa_verdict in the JSON response."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient

        from marketing_shorts_agent.main import app

        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    def _payload(self) -> dict:
        return {
            "ticker": "7203",
            "company_name": "テスト株式会社",
            "sector": "製造業",
            "figures": [{"label": "PER", "value": "12.3x"}],
        }

    def test_qa_verdict_present_in_response(self, client):
        """POST /pipeline/run response must include qa_verdict field."""
        resp = client.post("/pipeline/run", json=self._payload())
        assert resp.status_code == 200
        body = resp.json()
        assert "qa_verdict" in body, "qa_verdict must be in the pipeline response"

    def test_qa_verdict_is_pass_in_stub_mode(self, client):
        """Default stub mode → qa_verdict.verdict == 'pass'."""
        resp = client.post("/pipeline/run", json=self._payload())
        assert resp.status_code == 200
        body = resp.json()
        qa = body.get("qa_verdict")
        assert qa is not None
        assert qa["verdict"] == "pass"

    def test_qa_verdict_has_deterministic_checks(self, client):
        """qa_verdict must include deterministic_checks list."""
        resp = client.post("/pipeline/run", json=self._payload())
        assert resp.status_code == 200
        qa = resp.json().get("qa_verdict", {})
        assert isinstance(qa.get("deterministic_checks"), list)
        assert len(qa["deterministic_checks"]) > 0

    def test_landing_page_mentions_video_qa(self, client):
        """Landing page pipeline list must mention Video QA."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Video QA" in resp.text
