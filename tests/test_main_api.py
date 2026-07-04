"""Tests for marketing_shorts_agent.main — FastAPI application.

All tests run in bundled-stub mode: no network, no API keys required.
The lifespan fixture starts bundled stubs in-process once per module.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marketing_shorts_agent.main import app


# ── Shared client (lifespan fires once per module) ────────────────────────────


@pytest.fixture(scope="module")
def client() -> TestClient:
    """FastAPI TestClient with lifespan — starts bundled stubs in-process.

    Using ``with`` triggers ``_lifespan`` which builds the PipelineOrchestrator
    (and any bundled stubs) before tests run.
    """
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Helper ────────────────────────────────────────────────────────────────────


def _stock_payload() -> dict:
    """Minimal valid StockInfoRequest payload."""
    return {
        "ticker": "7203",
        "company_name": "テスト株式会社",
        "sector": "製造業",
        "figures": [
            {"label": "PER", "value": "12.3x"},
            {"label": "PBR", "value": "1.5x"},
            {"label": "売上高", "value": "¥3,000億"},
        ],
    }


# ── GET /healthz ──────────────────────────────────────────────────────────────


class TestHealthz:
    def test_returns_200(self, client: TestClient) -> None:
        """Health endpoint must return HTTP 200."""
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_body_is_ok(self, client: TestClient) -> None:
        """Health endpoint must return ``{"status": "ok"}``."""
        resp = client.get("/healthz")
        assert resp.json() == {"status": "ok"}


# ── GET / ─────────────────────────────────────────────────────────────────────


class TestLandingPage:
    def test_returns_200(self, client: TestClient) -> None:
        """Landing page must return HTTP 200."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_content_type_is_html(self, client: TestClient) -> None:
        """Landing page must return HTML."""
        resp = client.get("/")
        assert "text/html" in resp.headers.get("content-type", "")

    def test_contains_agent_name(self, client: TestClient) -> None:
        """Landing page must mention the agent name."""
        resp = client.get("/")
        assert "marketing-shorts-agent" in resp.text

    def test_links_to_docs(self, client: TestClient) -> None:
        """Landing page must link to /docs."""
        resp = client.get("/")
        assert "/docs" in resp.text

    def test_lists_pipeline_stages(self, client: TestClient) -> None:
        """Landing page must list pipeline stage entries."""
        resp = client.get("/")
        body = resp.text
        # At least one stage entry expected
        assert "Content generation" in body
        assert "YMYL guard" in body
        assert "Renderer" in body


# ── POST /pipeline/run — stub-mode E2E ───────────────────────────────────────


class TestPipelineRun:
    def test_succeeds_in_stub_mode(self, client: TestClient) -> None:
        """Full pipeline in bundled-stub mode returns HTTP 200 and success."""
        resp = client.post("/pipeline/run", json=_stock_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_ticker_echoed_in_response(self, client: TestClient) -> None:
        """Response ticker must match the request ticker."""
        resp = client.post("/pipeline/run", json=_stock_payload())
        assert resp.status_code == 200
        assert resp.json()["ticker"] == "7203"

    def test_render_job_state_is_done(self, client: TestClient) -> None:
        """Renderer-stub completes synchronously; state must be 'done'."""
        resp = client.post("/pipeline/run", json=_stock_payload())
        assert resp.status_code == 200
        assert resp.json()["render_job_state"] == "done"

    def test_response_has_version_id(self, client: TestClient) -> None:
        """Pipeline must register a version; version_id must be non-empty."""
        resp = client.post("/pipeline/run", json=_stock_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["version_id"], "version_id must not be empty"

    def test_dry_run_publish_result(self, client: TestClient) -> None:
        """Default DRY_RUN=true → publish_result.dry_run is True."""
        resp = client.post("/pipeline/run", json=_stock_payload())
        assert resp.status_code == 200
        body = resp.json()
        pub = body.get("publish_result")
        assert pub is not None, "publish_result must be present"
        assert pub["dry_run"] is True

    def test_no_errors_in_stub_mode(self, client: TestClient) -> None:
        """No pipeline errors expected in bundled-stub mode."""
        resp = client.post("/pipeline/run", json=_stock_payload())
        assert resp.status_code == 200
        assert resp.json()["errors"] == []

    # ── Invalid input → 422 ───────────────────────────────────────────────────

    def test_missing_all_fields_returns_422(self, client: TestClient) -> None:
        """Empty body → 422 Unprocessable Entity."""
        resp = client.post("/pipeline/run", json={})
        assert resp.status_code == 422

    def test_missing_required_fields_returns_422(self, client: TestClient) -> None:
        """Body with only ticker (missing company_name, sector, figures) → 422."""
        resp = client.post("/pipeline/run", json={"ticker": "7203"})
        assert resp.status_code == 422

    def test_invalid_figures_type_returns_422(self, client: TestClient) -> None:
        """figures must be a list of objects; a plain string → 422."""
        payload = {
            "ticker": "7203",
            "company_name": "テスト",
            "sector": "製造業",
            "figures": "not-a-list",
        }
        resp = client.post("/pipeline/run", json=payload)
        assert resp.status_code == 422
