"""Tests for agentops-platform HTTP clients (version register, analytics, evaluator).

All tests use httpx mocking (pytest-httpx) — no real network calls are made.
dry_run=True is tested (no HTTP), dry_run=False is tested with mocked responses.
"""

from __future__ import annotations

import hashlib

import pytest
from pytest_httpx import HTTPXMock

from marketing_shorts_agent.analytics.client import AgentOpsAnalyticsClient
from marketing_shorts_agent.analytics.interface import VideoMetrics
from marketing_shorts_agent.evaluator.agentops_client import AgentOpsEvaluatorClient
from marketing_shorts_agent.models import (
    FigureItem,
    Script,
    ScriptSegment,
    ScriptShotType,
)
from marketing_shorts_agent.version_register.client import AgentOpsVersionRegisterClient
from marketing_shorts_agent.version_register.interface import VersionRecord

_BASE_URL = "https://agentops-test.run.app/v1"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def version_record() -> VersionRecord:
    return VersionRecord(
        agent_id="marketing-shorts-agent",
        version="1.0.0",
        content_generator_class="ExampleContentGenerator",
        metadata={"image": "gcr.io/test/agent:sha256", "model": "gemini-2.0-flash-001"},
    )


@pytest.fixture
def sample_metrics() -> VideoMetrics:
    return VideoMetrics(
        video_id="yt-video-abc123",
        views=1000,
        average_view_duration_sec=42.5,
        retention_rate=0.71,
        likes=55,
    )


@pytest.fixture
def sample_script() -> Script:
    return Script(
        ticker="7203",
        title="Test script",
        segments=[
            ScriptSegment(type=ScriptShotType.HOOK, text="Hook text"),
            ScriptSegment(
                type=ScriptShotType.FIGURES,
                text="Figures",
                figures=[FigureItem(label="PER", value="12.3x")],
            ),
            ScriptSegment(
                type=ScriptShotType.DISCLAIMER,
                text="This is not investment advice.",
            ),
        ],
    )


# ── VersionRegisterClient ─────────────────────────────────────────────────────


class TestVersionRegisterClientDryRun:
    """dry_run=True skips HTTP and returns deterministic mock id."""

    def test_register_returns_mock_id_without_http(self, version_record: VersionRecord):
        client = AgentOpsVersionRegisterClient(
            base_url=_BASE_URL,
            dry_run=True,
        )
        result = client.register(version_record)
        assert result.startswith("mock-ver-"), f"Expected mock-ver-* prefix, got: {result}"

    def test_register_is_deterministic(self, version_record: VersionRecord):
        """Same input always returns the same mock id."""
        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=True)
        id1 = client.register(version_record)
        id2 = client.register(version_record)
        assert id1 == id2

    def test_different_versions_produce_different_ids(self, version_record: VersionRecord):
        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=True)
        r1 = version_record
        r2 = VersionRecord(
            agent_id=r1.agent_id,
            version="2.0.0",
            content_generator_class=r1.content_generator_class,
        )
        assert client.register(r1) != client.register(r2)


class TestVersionRegisterClientLive:
    """dry_run=False issues real HTTP (mocked with pytest-httpx)."""

    def test_register_posts_to_agents_then_versions(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        # Mock POST /agents → 201
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents",
            status_code=201,
            json={"agentId": "plat-agent-001", "name": "marketing-shorts-agent", "runtime": "adk-cloud-run", "createdAt": "2026-01-01T00:00:00Z"},
        )
        # Mock POST /agents/plat-agent-001/versions → 201
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/plat-agent-001/versions",
            status_code=201,
            json={"versionId": "v-xyz123", "createdAt": "2026-01-01T00:00:00Z"},
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        result = client.register(version_record)
        assert result == "v-xyz123"

    def test_register_handles_409_conflict_on_agent(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """When POST /agents returns 409, client falls back to GET /agents to find agentId."""
        # POST /agents → 409 (already exists)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents",
            status_code=409,
            json={"code": "CONFLICT", "message": "already exists"},
        )
        # GET /agents → list containing the agent
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": "existing-agent-id", "name": "marketing-shorts-agent", "runtime": "adk-cloud-run"}],
        )
        # POST /agents/existing-agent-id/versions → 201
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/existing-agent-id/versions",
            status_code=201,
            json={"versionId": "v-existing-001", "createdAt": "2026-01-01T00:00:00Z"},
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        result = client.register(version_record)
        assert result == "v-existing-001"

    def test_register_builds_correct_payload(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """The version payload must include image, model, and promptDigest."""
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents",
            status_code=201,
            json={"agentId": "a1", "name": "marketing-shorts-agent", "runtime": "adk-cloud-run", "createdAt": "2026-01-01T00:00:00Z"},
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/a1/versions",
            status_code=201,
            json={"versionId": "v1", "createdAt": "2026-01-01T00:00:00Z"},
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        client.register(version_record)

        # Inspect the second request (POST /versions)
        requests = httpx_mock.get_requests()
        version_req = requests[1]
        import json
        body = json.loads(version_req.content)
        assert "image" in body
        assert "model" in body
        assert "promptDigest" in body
        expected_digest = hashlib.sha256(
            version_record.content_generator_class.encode()
        ).hexdigest()[:16]
        assert body["promptDigest"] == expected_digest


# ── AgentOpsAnalyticsClient ───────────────────────────────────────────────────


class TestAnalyticsClientDryRun:
    """dry_run=True skips HTTP."""

    def test_pull_returns_zero_metrics(self, sample_metrics: VideoMetrics):
        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=True)
        result = client.pull("any-video-id")
        assert result.views == 0
        assert result.retention_rate == 0.0

    def test_push_does_not_raise_in_dry_run(self, sample_metrics: VideoMetrics):
        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=True)
        client.push(sample_metrics, "marketing-shorts-agent")  # must not raise


class TestAnalyticsClientLive:
    """dry_run=False issues real HTTP (mocked)."""

    def test_push_posts_to_metrics_endpoint(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, "marketing-shorts-agent")  # must not raise

    def test_push_payload_contains_required_fields(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        """MetricIngest payload must have versionId, source, and samples."""
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, "marketing-shorts-agent")

        import json
        req = httpx_mock.get_requests()[0]
        body = json.loads(req.content)
        assert "versionId" in body
        assert body["source"] == "youtube-analytics"
        assert isinstance(body["samples"], list)
        assert len(body["samples"]) >= 4

    def test_push_payload_sample_names(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        """Payload must include retention_rate, views, average_view_duration_sec, likes."""
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, "marketing-shorts-agent")

        import json
        req = httpx_mock.get_requests()[0]
        body = json.loads(req.content)
        names = {s["name"] for s in body["samples"]}
        assert "retention_rate" in names
        assert "views" in names
        assert "average_view_duration_sec" in names
        assert "likes" in names

    def test_push_payload_values_match_metrics(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        """Sample values in the payload must match the input VideoMetrics."""
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, "marketing-shorts-agent")

        import json
        req = httpx_mock.get_requests()[0]
        body = json.loads(req.content)
        by_name = {s["name"]: s["value"] for s in body["samples"]}
        assert by_name["retention_rate"] == pytest.approx(0.71)
        assert by_name["views"] == pytest.approx(1000.0)
        assert by_name["average_view_duration_sec"] == pytest.approx(42.5)
        assert by_name["likes"] == pytest.approx(55.0)


# ── AgentOpsEvaluatorClient ───────────────────────────────────────────────────


class TestEvaluatorClientDryRun:
    """dry_run=True returns passing mock EvalResult without HTTP."""

    def test_evaluate_returns_passing_result(self, sample_script: Script):
        client = AgentOpsEvaluatorClient(
            base_url=_BASE_URL,
            agent_id="marketing-shorts-agent",
            suite_id="suite-001",
            version_id="v-001",
            dry_run=True,
        )
        result = client.evaluate(sample_script)
        assert result.passed is True
        assert result.score == 1.0
        assert "dry-run" in result.notes


class TestEvaluatorClientLive:
    """dry_run=False issues real HTTP (mocked)."""

    def test_evaluate_starts_evaluation_and_polls(
        self,
        httpx_mock: HTTPXMock,
        sample_script: Script,
    ):
        agent_id = "marketing-shorts-agent"
        suite_id = "suite-001"
        version_id = "v-001"
        evaluation_id = "eval-abc"

        # Mock POST /agents/{id}/evaluations → 202
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{agent_id}/evaluations",
            status_code=202,
            json={
                "evaluationId": evaluation_id,
                "versionId": version_id,
                "suiteId": suite_id,
                "state": "queued",
            },
        )
        # Mock GET /evaluations/{id} → succeeded
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/evaluations/{evaluation_id}",
            status_code=200,
            json={
                "evaluationId": evaluation_id,
                "versionId": version_id,
                "suiteId": suite_id,
                "state": "succeeded",
                "scores": [
                    {"axis": "drift", "score": 0.92, "threshold": 0.8, "pass": True},
                    {"axis": "trajectory", "score": 0.88, "threshold": 0.75, "pass": True},
                ],
            },
        )

        client = AgentOpsEvaluatorClient(
            base_url=_BASE_URL,
            agent_id=agent_id,
            suite_id=suite_id,
            version_id=version_id,
            dry_run=False,
        )
        result = client.evaluate(sample_script)
        assert result.passed is True
        # Overall score = mean of ALL axis scores (drift=0.92, trajectory=0.88)
        assert result.score == pytest.approx((0.92 + 0.88) / 2, rel=1e-3)
        assert "succeeded" in result.notes

    def test_evaluate_failed_state_returns_not_passed(
        self,
        httpx_mock: HTTPXMock,
        sample_script: Script,
    ):
        agent_id = "marketing-shorts-agent"
        evaluation_id = "eval-fail"

        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{agent_id}/evaluations",
            status_code=202,
            json={"evaluationId": evaluation_id, "versionId": "v-001", "suiteId": "s-001", "state": "queued"},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/evaluations/{evaluation_id}",
            status_code=200,
            json={
                "evaluationId": evaluation_id,
                "versionId": "v-001",
                "suiteId": "s-001",
                "state": "failed",
                "scores": [
                    {"axis": "drift", "score": 0.55, "threshold": 0.8, "pass": False},
                ],
            },
        )

        client = AgentOpsEvaluatorClient(
            base_url=_BASE_URL,
            agent_id=agent_id,
            suite_id="s-001",
            version_id="v-001",
            dry_run=False,
        )
        result = client.evaluate(sample_script)
        assert result.passed is False
        assert len(result.violations) > 0


# ── Regression: evaluator overall score includes all axes ────────────────────


class TestEvaluatorOverallScoreIncludesAllAxes:
    """Regression tests: overall score must reflect drift AND trajectory axes."""

    def test_overall_is_mean_of_drift_and_trajectory(
        self,
        httpx_mock: HTTPXMock,
        sample_script: Script,
    ):
        """When both drift and trajectory are present, score = (drift + trajectory) / 2."""
        agent_id = "marketing-shorts-agent"
        evaluation_id = "eval-axes"

        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{agent_id}/evaluations",
            status_code=202,
            json={"evaluationId": evaluation_id, "versionId": "v-001", "suiteId": "s-001", "state": "queued"},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/evaluations/{evaluation_id}",
            status_code=200,
            json={
                "evaluationId": evaluation_id,
                "versionId": "v-001",
                "suiteId": "s-001",
                "state": "succeeded",
                "scores": [
                    {"axis": "drift", "score": 0.80, "threshold": 0.8, "pass": True},
                    {"axis": "trajectory", "score": 0.60, "threshold": 0.5, "pass": True},
                ],
            },
        )

        client = AgentOpsEvaluatorClient(
            base_url=_BASE_URL,
            agent_id=agent_id,
            suite_id="s-001",
            version_id="v-001",
            dry_run=False,
        )
        result = client.evaluate(sample_script)
        assert result.passed is True
        # Must be the mean of both axes, not just drift
        assert result.score == pytest.approx((0.80 + 0.60) / 2, rel=1e-3)

    def test_drift_only_still_works(
        self,
        httpx_mock: HTTPXMock,
        sample_script: Script,
    ):
        """When only drift is present, score equals the drift score (backward-compat)."""
        agent_id = "marketing-shorts-agent"
        evaluation_id = "eval-drift-only"

        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{agent_id}/evaluations",
            status_code=202,
            json={"evaluationId": evaluation_id, "versionId": "v-001", "suiteId": "s-001", "state": "queued"},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/evaluations/{evaluation_id}",
            status_code=200,
            json={
                "evaluationId": evaluation_id,
                "state": "succeeded",
                "scores": [
                    {"axis": "drift", "score": 0.75, "threshold": 0.7, "pass": True},
                ],
            },
        )

        client = AgentOpsEvaluatorClient(
            base_url=_BASE_URL,
            agent_id=agent_id,
            suite_id="s-001",
            version_id="v-001",
            dry_run=False,
        )
        result = client.evaluate(sample_script)
        assert result.score == pytest.approx(0.75, rel=1e-3)

    def test_no_scores_succeeds_with_1_0(
        self,
        httpx_mock: HTTPXMock,
        sample_script: Script,
    ):
        """When no score entries exist and state=succeeded, score defaults to 1.0."""
        agent_id = "marketing-shorts-agent"
        evaluation_id = "eval-no-scores"

        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{agent_id}/evaluations",
            status_code=202,
            json={"evaluationId": evaluation_id, "versionId": "v-001", "suiteId": "s-001", "state": "queued"},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/evaluations/{evaluation_id}",
            status_code=200,
            json={"evaluationId": evaluation_id, "state": "succeeded", "scores": []},
        )

        client = AgentOpsEvaluatorClient(
            base_url=_BASE_URL,
            agent_id=agent_id,
            suite_id="s-001",
            version_id="v-001",
            dry_run=False,
        )
        result = client.evaluate(sample_script)
        assert result.passed is True
        assert result.score == pytest.approx(1.0)


# ── Regression: analytics versionId is populated from version register ────────


class TestAnalyticsVersionIdPropagation:
    """Regression: versionId in MetricIngest must come from version register, not agent_id fallback."""

    def test_push_uses_version_id_from_extra_when_present(
        self,
        httpx_mock: HTTPXMock,
    ):
        """When metrics.extra contains version_id, the payload versionId matches it."""
        import json
        from marketing_shorts_agent.analytics.interface import VideoMetrics

        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        metrics = VideoMetrics(
            video_id="yt-abc",
            views=100,
            average_view_duration_sec=30.0,
            retention_rate=0.5,
            likes=10,
            extra={"version_id": "v-from-register-001"},
        )
        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(metrics, "marketing-shorts-agent")

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["versionId"] == "v-from-register-001"

    def test_push_uses_empty_string_when_version_id_absent(
        self,
        httpx_mock: HTTPXMock,
    ):
        """When version_id is absent from extra, versionId is an empty string (not agent_id)."""
        import json
        from marketing_shorts_agent.analytics.interface import VideoMetrics

        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/marketing-shorts-agent/metrics",
            status_code=202,
        )

        metrics = VideoMetrics(video_id="yt-xyz", views=0, average_view_duration_sec=0.0, retention_rate=0.0, likes=0)
        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(metrics, "marketing-shorts-agent")

        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["versionId"] == ""
        assert body["versionId"] != "marketing-shorts-agent"


# ── Regression: renderer_stub duration is shot-based ─────────────────────────
