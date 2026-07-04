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
_AGENT_NAME = "marketing-shorts-agent"
_AGENT_UUID = "plat-agent-uuid-001"


def _mock_agent_list(httpx_mock: HTTPXMock, uuid: str = _AGENT_UUID) -> None:
    """Register a GET /agents mock that returns a list containing the test agent."""
    httpx_mock.add_response(
        method="GET",
        url=f"{_BASE_URL}/agents",
        status_code=200,
        json=[{"agentId": uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
    )


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

    def test_register_no_existing_agent_issues_get_then_post(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """When GET /agents returns an empty list, POST /agents is called to create the agent."""
        # GET /agents → empty list (agent does not exist yet)
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[],
        )
        # POST /agents → 201 (create)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents",
            status_code=201,
            json={"agentId": "plat-agent-001", "name": "marketing-shorts-agent", "runtime": "adk-cloud-run", "createdAt": "2026-01-01T00:00:00Z"},
        )
        # POST /agents/plat-agent-001/versions → 201
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/plat-agent-001/versions",
            status_code=201,
            json={"versionId": "v-xyz123", "createdAt": "2026-01-01T00:00:00Z"},
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        result = client.register(version_record)
        assert result == "v-xyz123"

        requests = httpx_mock.get_requests()
        # First request must be GET /agents (search before create)
        assert requests[0].method == "GET"
        assert str(requests[0].url).endswith("/agents")
        # Second request must be POST /agents (create)
        assert requests[1].method == "POST"
        assert str(requests[1].url).endswith("/agents")

    def test_register_existing_agent_skips_post(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """When GET /agents returns a matching agent, POST /agents must NOT be called."""
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

        requests = httpx_mock.get_requests()
        # Only 2 requests: GET /agents + POST /agents/{id}/versions (no POST /agents)
        assert len(requests) == 2
        assert requests[0].method == "GET"
        assert str(requests[0].url).endswith("/agents")
        assert requests[1].method == "POST"
        assert "existing-agent-id" in str(requests[1].url)

    def test_register_uses_cache_on_second_call(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """Second call to register() reuses the cached agentId — no GET issued again."""
        # GET /agents → empty list (first call only)
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[],
        )
        # POST /agents → 201 (first call only)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents",
            status_code=201,
            json={"agentId": "cached-agent-id", "name": "marketing-shorts-agent", "runtime": "adk-cloud-run", "createdAt": "2026-01-01T00:00:00Z"},
        )
        # POST versions for first call
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/cached-agent-id/versions",
            status_code=201,
            json={"versionId": "v-first", "createdAt": "2026-01-01T00:00:00Z"},
        )
        # POST versions for second call (no GET or POST /agents needed)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/cached-agent-id/versions",
            status_code=201,
            json={"versionId": "v-second", "createdAt": "2026-01-01T00:00:00Z"},
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        r1 = client.register(version_record)
        r2 = client.register(version_record)
        assert r1 == "v-first"
        assert r2 == "v-second"

        requests = httpx_mock.get_requests()
        # GET /agents: 1 time, POST /agents: 1 time, POST versions: 2 times
        get_agents = [r for r in requests if r.method == "GET" and str(r.url).endswith("/agents")]
        post_agents = [r for r in requests if r.method == "POST" and str(r.url).endswith("/agents")]
        assert len(get_agents) == 1, "GET /agents must be issued only once (cache used on 2nd call)"
        assert len(post_agents) == 1, "POST /agents must be issued only once"

    def test_register_builds_correct_payload(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """The version payload must include image, model, and promptDigest."""
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[],
        )
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

        # Inspect the last request (POST /versions)
        requests = httpx_mock.get_requests()
        version_req = requests[-1]
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
    """dry_run=False issues real HTTP (mocked).

    The client now resolves the agent name to a UUID (GET /agents) before
    posting to /agents/{uuid}/metrics.  All tests in this class must mock
    the GET /agents call first.
    """

    def test_push_posts_to_uuid_metrics_endpoint(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        """push() must resolve the UUID via GET /agents and use it in the path."""
        _mock_agent_list(httpx_mock)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{_AGENT_UUID}/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, _AGENT_NAME)  # must not raise

        requests = httpx_mock.get_requests()
        assert requests[0].method == "GET"
        assert str(requests[0].url).endswith("/agents")
        assert requests[1].method == "POST"
        assert _AGENT_UUID in str(requests[1].url)
        assert _AGENT_NAME not in str(requests[1].url), (
            "The metrics path must use the UUID, not the agent name"
        )

    def test_push_payload_contains_required_fields(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        """MetricIngest payload must have versionId, source, and samples."""
        _mock_agent_list(httpx_mock)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{_AGENT_UUID}/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, _AGENT_NAME)

        import json
        req = httpx_mock.get_requests()[-1]  # last request is the POST /metrics
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
        _mock_agent_list(httpx_mock)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{_AGENT_UUID}/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, _AGENT_NAME)

        import json
        req = httpx_mock.get_requests()[-1]
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
        _mock_agent_list(httpx_mock)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{_AGENT_UUID}/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, _AGENT_NAME)

        import json
        req = httpx_mock.get_requests()[-1]
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

        _mock_agent_list(httpx_mock)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{_AGENT_UUID}/metrics",
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
        client.push(metrics, _AGENT_NAME)

        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["versionId"] == "v-from-register-001"

    def test_push_uses_empty_string_when_version_id_absent(
        self,
        httpx_mock: HTTPXMock,
    ):
        """When version_id is absent from extra, versionId is an empty string (not agent_id)."""
        import json
        from marketing_shorts_agent.analytics.interface import VideoMetrics

        _mock_agent_list(httpx_mock)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{_AGENT_UUID}/metrics",
            status_code=202,
        )

        metrics = VideoMetrics(video_id="yt-xyz", views=0, average_view_duration_sec=0.0, retention_rate=0.0, likes=0)
        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(metrics, _AGENT_NAME)

        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["versionId"] == ""
        assert body["versionId"] != _AGENT_NAME


# ── Bug fix: version POST 404 → stale-cache recovery ─────────────────────────


class TestVersionRegisterStaleCache:
    """Bug fix (a)(b): version POST 404 triggers cache invalidation + one retry."""

    def test_version_post_404_triggers_re_ensure_and_retry_success(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """(a) When version POST returns 404 (stale agentId), the client invalidates
        the cache, re-ensures the agent, and retries the POST exactly once."""
        stale_uuid = "stale-agent-uuid-old"
        fresh_uuid = "fresh-agent-uuid-new"

        # First agent resolution (GET /agents → stale uuid still in list initially)
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": stale_uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
        )
        # Version POST with stale uuid → 404 (platform was restarted)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{stale_uuid}/versions",
            status_code=404,
            json={"error": "agent not found"},
        )
        # Re-ensure: GET /agents now returns the fresh uuid (or empty → POST creates)
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": fresh_uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
        )
        # Retry version POST with fresh uuid → success
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{fresh_uuid}/versions",
            status_code=201,
            json={"versionId": "v-retry-success", "createdAt": "2026-01-01T00:00:00Z"},
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        result = client.register(version_record)
        assert result == "v-retry-success"

        requests = httpx_mock.get_requests()
        # Request sequence: GET, POST(404), GET(re-resolve), POST(retry)
        assert requests[0].method == "GET"   # initial resolve
        assert requests[1].method == "POST"  # stale version POST (404)
        assert requests[2].method == "GET"   # re-resolve after cache invalidation
        assert requests[3].method == "POST"  # retry with fresh uuid
        assert fresh_uuid in str(requests[3].url)

    def test_version_post_404_retry_also_fails_raises_non_fatally(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """(b) When the retry also fails, the exception propagates (non-fatal to
        the pipeline, but the client itself raises so the caller can decide)."""
        stale_uuid = "stale-uuid-both-fail"
        fresh_uuid = "fresh-uuid-both-fail"

        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": stale_uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{stale_uuid}/versions",
            status_code=404,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": fresh_uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
        )
        # Retry also returns 404
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{fresh_uuid}/versions",
            status_code=404,
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        import httpx as _httpx
        with pytest.raises(_httpx.HTTPStatusError) as exc_info:
            client.register(version_record)
        assert exc_info.value.response.status_code == 404

    def test_version_post_non_404_error_is_not_retried(
        self,
        httpx_mock: HTTPXMock,
        version_record: VersionRecord,
    ):
        """Non-404 HTTP errors (e.g., 500) are re-raised immediately without retry."""
        some_uuid = "agent-uuid-500"

        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": some_uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{some_uuid}/versions",
            status_code=500,
        )

        client = AgentOpsVersionRegisterClient(base_url=_BASE_URL, dry_run=False)
        import httpx as _httpx
        with pytest.raises(_httpx.HTTPStatusError) as exc_info:
            client.register(version_record)
        assert exc_info.value.response.status_code == 500

        requests = httpx_mock.get_requests()
        # Only 2 requests: GET /agents + POST /versions (no retry)
        assert len(requests) == 2


# ── Bug fix: analytics uses resolved UUID path ────────────────────────────────


class TestAnalyticsStaleCache:
    """Bug fix (c)(d): analytics push uses UUID path and recovers from 404."""

    def test_push_uses_resolved_uuid_not_agent_name(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        """(c) metrics path must be /agents/{uuid}/metrics, not /agents/{name}/metrics."""
        _mock_agent_list(httpx_mock)
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{_AGENT_UUID}/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, _AGENT_NAME)

        requests = httpx_mock.get_requests()
        metrics_req = requests[-1]
        assert metrics_req.method == "POST"
        assert _AGENT_UUID in str(metrics_req.url)
        # Critically, the raw agent name must NOT appear in the path
        assert f"/agents/{_AGENT_NAME}/metrics" not in str(metrics_req.url)

    def test_push_metrics_404_triggers_re_resolve_and_retry(
        self,
        httpx_mock: HTTPXMock,
        sample_metrics: VideoMetrics,
    ):
        """(d) When metrics POST returns 404 (stale uuid), the client re-resolves
        and retries with the fresh uuid exactly once."""
        stale_uuid = "stale-metrics-uuid-old"
        fresh_uuid = "fresh-metrics-uuid-new"

        # Initial GET /agents → stale uuid
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": stale_uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
        )
        # metrics POST with stale uuid → 404
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{stale_uuid}/metrics",
            status_code=404,
        )
        # Re-resolve GET /agents → fresh uuid
        httpx_mock.add_response(
            method="GET",
            url=f"{_BASE_URL}/agents",
            status_code=200,
            json=[{"agentId": fresh_uuid, "name": _AGENT_NAME, "runtime": "adk-cloud-run"}],
        )
        # Retry with fresh uuid → success
        httpx_mock.add_response(
            method="POST",
            url=f"{_BASE_URL}/agents/{fresh_uuid}/metrics",
            status_code=202,
        )

        client = AgentOpsAnalyticsClient(base_url=_BASE_URL, dry_run=False)
        client.push(sample_metrics, _AGENT_NAME)  # must not raise

        requests = httpx_mock.get_requests()
        assert requests[0].method == "GET"   # initial resolve
        assert requests[1].method == "POST"  # stale metrics POST (404)
        assert requests[2].method == "GET"   # re-resolve
        assert requests[3].method == "POST"  # retry with fresh uuid
        assert fresh_uuid in str(requests[3].url)


# ── Regression: renderer_stub duration is shot-based ─────────────────────────
