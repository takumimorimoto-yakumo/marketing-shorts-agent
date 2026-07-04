"""Tests for AgentOps client wiring in main._build_orchestrator().

Verifies:
- When AGENTOPS_BASE_URL is set, real clients are injected into PipelineConfig.
- When AGENTOPS_BASE_URL is unset, stub implementations are used.
- Send payload shape for version register and analytics is correct.
- Pipeline continues (success=True, errors=[]) when agentops calls fail.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from pytest_httpx import HTTPXMock

from marketing_shorts_agent.analytics.client import AgentOpsAnalyticsClient
from marketing_shorts_agent.analytics.stub import AnalyticsStub
from marketing_shorts_agent.main import _build_orchestrator
from marketing_shorts_agent.pipeline import PipelineConfig
from marketing_shorts_agent.version_register.client import AgentOpsVersionRegisterClient
from marketing_shorts_agent.version_register.stub import VersionRegisterStub

_AGENTOPS_URL = "https://agentops-platform-nk3aomvl6q-an.a.run.app"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _env_with_agentops(
    base_url: str = _AGENTOPS_URL,
    agent_id: str = "marketing-shorts-agent",
    api_key: str = "",
) -> dict[str, str]:
    """Return os.environ overrides with AgentOps variables set."""
    return {
        "AGENTOPS_BASE_URL": base_url,
        "AGENTOPS_AGENT_ID": agent_id,
        "AGENTOPS_API_KEY": api_key,
        # Minimal overrides so _build_orchestrator can complete without starting stubs
        "RENDERER_URL": "http://127.0.0.1:18080/v1",
    }


# ── Client selection ──────────────────────────────────────────────────────────


class TestClientSelection:
    """_build_orchestrator injects real vs stub clients based on AGENTOPS_BASE_URL."""

    def test_real_clients_injected_when_base_url_set(self) -> None:
        """When AGENTOPS_BASE_URL is set, version_register and analytics must be live clients."""
        env = _env_with_agentops()
        with patch.dict(os.environ, env, clear=False):
            orchestrator = _build_orchestrator()

        config: PipelineConfig = orchestrator._config
        assert isinstance(config.version_register, AgentOpsVersionRegisterClient), (
            f"Expected AgentOpsVersionRegisterClient, got {type(config.version_register)}"
        )
        assert isinstance(config.analytics, AgentOpsAnalyticsClient), (
            f"Expected AgentOpsAnalyticsClient, got {type(config.analytics)}"
        )

    def test_stub_clients_used_when_base_url_empty(self) -> None:
        """When AGENTOPS_BASE_URL is absent, version_register and analytics must be stubs."""
        env = {"AGENTOPS_BASE_URL": "", "RENDERER_URL": "http://127.0.0.1:18080/v1"}
        with patch.dict(os.environ, env, clear=False):
            orchestrator = _build_orchestrator()

        config: PipelineConfig = orchestrator._config
        # None in config → orchestrator falls back to stubs
        assert config.version_register is None or isinstance(
            config.version_register, VersionRegisterStub
        ), f"Expected None or VersionRegisterStub, got {type(config.version_register)}"
        assert config.analytics is None or isinstance(
            config.analytics, AnalyticsStub
        ), f"Expected None or AnalyticsStub, got {type(config.analytics)}"

    def test_agent_id_forwarded_to_config(self) -> None:
        """AGENTOPS_AGENT_ID must be forwarded to PipelineConfig.agent_id."""
        env = _env_with_agentops(agent_id="custom-agent-name")
        with patch.dict(os.environ, env, clear=False):
            orchestrator = _build_orchestrator()

        assert orchestrator._config.agent_id == "custom-agent-name"

    def test_default_agent_id_when_env_unset(self) -> None:
        """When AGENTOPS_AGENT_ID is not set, default is 'marketing-shorts-agent'."""
        env = {"RENDERER_URL": "http://127.0.0.1:18080/v1"}
        with patch.dict(os.environ, env, clear=False):
            # Remove AGENTOPS_AGENT_ID if present
            env_clean = {k: v for k, v in os.environ.items() if k != "AGENTOPS_AGENT_ID"}
            env_clean["RENDERER_URL"] = "http://127.0.0.1:18080/v1"
            env_clean.pop("AGENTOPS_BASE_URL", None)
            with patch.dict(os.environ, env_clean, clear=True):
                orchestrator = _build_orchestrator()

        assert orchestrator._config.agent_id == "marketing-shorts-agent"


# ── Payload shape: version register ──────────────────────────────────────────


class TestVersionRegisterPayload:
    """Version register client sends correct payload to agentops-platform."""

    def test_register_posts_to_agents_endpoint(self, httpx_mock: HTTPXMock) -> None:
        """GET /v1/agents is called first; when no match, POST /v1/agents creates the agent."""
        # GET /agents → empty list (agent not yet registered)
        httpx_mock.add_response(
            method="GET",
            url=f"{_AGENTOPS_URL}/v1/agents",
            status_code=200,
            json=[],
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{_AGENTOPS_URL}/v1/agents",
            status_code=201,
            json={
                "agentId": "plat-agent-001",
                "name": "marketing-shorts-agent",
                "runtime": "adk-cloud-run",
                "createdAt": "2026-01-01T00:00:00Z",
            },
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{_AGENTOPS_URL}/v1/agents/plat-agent-001/versions",
            status_code=201,
            json={"versionId": "v-live-001", "createdAt": "2026-01-01T00:00:00Z"},
        )

        from marketing_shorts_agent.version_register.interface import VersionRecord

        client = AgentOpsVersionRegisterClient(
            base_url=f"{_AGENTOPS_URL}/v1",
            dry_run=False,
        )
        result = client.register(
            VersionRecord(
                agent_id="marketing-shorts-agent",
                version="0.1.0",
                content_generator_class="ExampleContentGenerator",
                metadata={"image": "gcr.io/test/agent:sha256", "model": "gemini-2.5-flash"},
            )
        )

        assert result == "v-live-001"
        requests = httpx_mock.get_requests()
        # First request: GET /agents (search before create)
        assert requests[0].method == "GET"
        # Second request: POST /agents (create — name and runtime must be set)
        agent_req_body = json.loads(requests[1].content)
        assert agent_req_body["name"] == "marketing-shorts-agent"
        assert agent_req_body["runtime"] == "adk-cloud-run"

    def test_version_payload_contains_required_fields(self, httpx_mock: HTTPXMock) -> None:
        """POST /agents/{id}/versions body must include image, model, and promptDigest."""
        # GET /agents → empty list (agent not yet registered)
        httpx_mock.add_response(
            method="GET",
            url=f"{_AGENTOPS_URL}/v1/agents",
            status_code=200,
            json=[],
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{_AGENTOPS_URL}/v1/agents",
            status_code=201,
            json={
                "agentId": "a1",
                "name": "marketing-shorts-agent",
                "runtime": "adk-cloud-run",
                "createdAt": "2026-01-01T00:00:00Z",
            },
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{_AGENTOPS_URL}/v1/agents/a1/versions",
            status_code=201,
            json={"versionId": "v1", "createdAt": "2026-01-01T00:00:00Z"},
        )

        from marketing_shorts_agent.version_register.interface import VersionRecord

        client = AgentOpsVersionRegisterClient(
            base_url=f"{_AGENTOPS_URL}/v1",
            dry_run=False,
        )
        client.register(
            VersionRecord(
                agent_id="marketing-shorts-agent",
                version="0.1.0",
                content_generator_class="ExampleContentGenerator",
                metadata={"image": "gcr.io/test/img:sha256", "model": "gemini-2.5-flash"},
            )
        )

        # Last request is POST /versions (index -1 regardless of GET/POST ordering)
        version_body = json.loads(httpx_mock.get_requests()[-1].content)
        assert "image" in version_body, "version payload must contain 'image'"
        assert "model" in version_body, "version payload must contain 'model'"
        assert "promptDigest" in version_body, "version payload must contain 'promptDigest'"
        # promptDigest must be a non-empty hex string
        assert len(version_body["promptDigest"]) > 0
        assert all(c in "0123456789abcdef" for c in version_body["promptDigest"])


# ── Payload shape: analytics ──────────────────────────────────────────────────


class TestAnalyticsPayload:
    """Analytics client sends correct MetricIngest payload to agentops-platform."""

    def test_push_hits_correct_endpoint(self, httpx_mock: HTTPXMock) -> None:
        """POST /v1/agents/{agentId}/metrics must be called."""
        httpx_mock.add_response(
            method="POST",
            url=f"{_AGENTOPS_URL}/v1/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        from marketing_shorts_agent.analytics.interface import VideoMetrics

        client = AgentOpsAnalyticsClient(base_url=f"{_AGENTOPS_URL}/v1", dry_run=False)
        client.push(
            VideoMetrics(
                video_id="yt-abc",
                views=100,
                average_view_duration_sec=30.0,
                retention_rate=0.5,
                likes=10,
                extra={"version_id": "v-live-001"},
            ),
            "marketing-shorts-agent",
        )

        assert len(httpx_mock.get_requests()) == 1

    def test_push_payload_schema(self, httpx_mock: HTTPXMock) -> None:
        """MetricIngest payload must have versionId, source='youtube-analytics', and samples."""
        httpx_mock.add_response(
            method="POST",
            url=f"{_AGENTOPS_URL}/v1/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        from marketing_shorts_agent.analytics.interface import VideoMetrics

        client = AgentOpsAnalyticsClient(base_url=f"{_AGENTOPS_URL}/v1", dry_run=False)
        metrics = VideoMetrics(
            video_id="yt-abc",
            views=500,
            average_view_duration_sec=45.0,
            retention_rate=0.72,
            likes=30,
            extra={"version_id": "v-live-xyz"},
        )
        client.push(metrics, "marketing-shorts-agent")

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["versionId"] == "v-live-xyz", (
            "versionId must be taken from metrics.extra['version_id']"
        )
        assert body["source"] == "youtube-analytics"
        assert isinstance(body["samples"], list) and len(body["samples"]) >= 4

        sample_names = {s["name"] for s in body["samples"]}
        assert "retention_rate" in sample_names
        assert "views" in sample_names
        assert "average_view_duration_sec" in sample_names
        assert "likes" in sample_names

        by_name = {s["name"]: s["value"] for s in body["samples"]}
        assert by_name["views"] == pytest.approx(500.0)
        assert by_name["retention_rate"] == pytest.approx(0.72)


# ── Pipeline resilience: agentops failure must not abort pipeline ─────────────


class TestPipelineResilienceOnAgentOpsFailure:
    """When agentops calls raise, the pipeline must complete with success=True."""

    def _stock_info(self):
        from marketing_shorts_agent.content import StockInfo
        from marketing_shorts_agent.models import FigureItem

        return StockInfo(
            ticker="9984",
            company_name="サンプル株式会社",
            sector="情報・通信業",
            figures=[
                FigureItem(label="PER", value="20.5x"),
                FigureItem(label="PBR", value="2.1x"),
                FigureItem(label="売上高", value="¥2,500億"),
            ],
        )

    def test_version_register_failure_does_not_abort_pipeline(self) -> None:
        """When version register raises, pipeline still returns success=True."""
        import threading

        import uvicorn

        from marketing_shorts_agent.analytics.stub import AnalyticsStub
        from marketing_shorts_agent.pipeline import PipelineOrchestrator
        from marketing_shorts_agent.version_register.interface import (
            VersionRecord,
            VersionRegisterInterface,
        )

        class _AlwaysFailVersionRegister(VersionRegisterInterface):
            def register(self, record: VersionRecord) -> str:
                raise RuntimeError("agentops-platform unavailable (simulated)")

        # Start renderer-stub on a free port
        from renderer_stub.app import app as _renderer_app

        from marketing_shorts_agent.pipeline.orchestrator import _allocate_port, _start_stub_server

        port = _allocate_port(28080)
        _start_stub_server(_renderer_app, "127.0.0.1", port)

        config = PipelineConfig(
            renderer_base_url=f"http://127.0.0.1:{port}/v1",
            dry_run=True,
            version_register=_AlwaysFailVersionRegister(),
            analytics=AnalyticsStub(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.success is True, (
            f"Pipeline must succeed even when version register fails; errors={result.errors}"
        )
        # version_id is empty string when register failed
        assert result.version_id == ""

    def test_analytics_failure_does_not_abort_pipeline(self) -> None:
        """When analytics push raises, pipeline still returns success=True."""
        from marketing_shorts_agent.analytics.interface import (
            AnalyticsInterface,
            VideoMetrics,
        )
        from marketing_shorts_agent.pipeline import PipelineOrchestrator
        from marketing_shorts_agent.version_register.stub import VersionRegisterStub

        class _AlwaysFailAnalytics(AnalyticsInterface):
            def pull(self, video_id: str) -> VideoMetrics:
                raise RuntimeError("analytics pull failed (simulated)")

            def push(self, metrics: VideoMetrics, agent_id: str) -> None:
                raise RuntimeError("analytics push failed (simulated)")

        from marketing_shorts_agent.pipeline.orchestrator import _allocate_port, _start_stub_server
        from renderer_stub.app import app as _renderer_app

        port = _allocate_port(28081)
        _start_stub_server(_renderer_app, "127.0.0.1", port)

        config = PipelineConfig(
            renderer_base_url=f"http://127.0.0.1:{port}/v1",
            dry_run=True,
            version_register=VersionRegisterStub(),
            analytics=_AlwaysFailAnalytics(),
        )
        orchestrator = PipelineOrchestrator(config)
        result = orchestrator.run(self._stock_info())

        assert result.success is True, (
            f"Pipeline must succeed even when analytics fails; errors={result.errors}"
        )
        assert result.version_id, "version_id must be registered before analytics error"
