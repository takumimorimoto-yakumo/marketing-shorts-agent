"""Tests for the content-stub service (content.openapi.yaml v1.0.0).

Verifies contract compliance:
1. Valid request → 200 + Script with disclaimer segment
2. Figure values are reproduced verbatim in the Script
3. Generated Script passes YMYL guard (no recommendation phrasing)
4. X-Contract-Version header is set to "1"
5. Missing required field → 422 (FastAPI validation)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marketing_shorts_agent.models import ScriptShotType


@pytest.fixture(autouse=True)
def client() -> TestClient:
    from content_stub.app import app

    return TestClient(app)


def _valid_payload() -> dict:
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


class TestContentStubContract:
    def test_valid_request_returns_200(self, client: TestClient):
        resp = client.post("/v1/scripts", json=_valid_payload())
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_response_has_script_fields(self, client: TestClient):
        resp = client.post("/v1/scripts", json=_valid_payload())
        body = resp.json()
        assert "ticker" in body
        assert "title" in body
        assert "segments" in body
        assert body["ticker"] == "7203"
        assert len(body["segments"]) >= 1

    def test_response_contains_disclaimer_segment(self, client: TestClient):
        resp = client.post("/v1/scripts", json=_valid_payload())
        body = resp.json()
        types = [s["type"] for s in body["segments"]]
        assert "disclaimer" in types, f"No disclaimer segment in: {types}"

    def test_figure_values_reproduced_verbatim(self, client: TestClient):
        """Figure values in the response must match the request exactly."""
        payload = _valid_payload()
        resp = client.post("/v1/scripts", json=payload)
        body = resp.json()

        # Collect figures from the response
        resp_figures: list[tuple[str, str]] = []
        for seg in body["segments"]:
            for fig in seg.get("figures", []):
                resp_figures.append((fig["label"], fig["value"]))

        # Every input figure must appear verbatim in the response
        expected = {(f["label"], f["value"]) for f in payload["figures"]}
        actual = set(resp_figures)
        missing = expected - actual
        assert not missing, f"Figure values missing or altered: {missing}"

    def test_x_contract_version_header(self, client: TestClient):
        resp = client.post("/v1/scripts", json=_valid_payload())
        assert resp.headers.get("x-contract-version") == "1", (
            f"Expected X-Contract-Version: 1, got: {resp.headers.get('x-contract-version')}"
        )

    def test_missing_required_field_returns_422(self, client: TestClient):
        """Omitting a required field triggers FastAPI schema validation → 422."""
        payload = _valid_payload()
        del payload["ticker"]
        resp = client.post("/v1/scripts", json=payload)
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_generated_script_passes_ymyl_guard(self, client: TestClient):
        """Generated script must pass the YMYL guard (no recommendation phrasing)."""
        from marketing_shorts_agent.models import Script, ScriptSegment, ScriptShotType, FigureItem
        from marketing_shorts_agent.guards.ymyl import check_script_ymyl

        resp = client.post("/v1/scripts", json=_valid_payload())
        body = resp.json()

        # Reconstruct Script domain model from wire format
        segments = [
            ScriptSegment(
                type=ScriptShotType(s["type"]),
                text=s["text"],
                figures=[FigureItem(label=f["label"], value=f["value"]) for f in s.get("figures", [])],
                duration_sec=s.get("duration_sec"),
            )
            for s in body["segments"]
        ]
        script = Script(ticker=body["ticker"], title=body["title"], segments=segments)

        result = check_script_ymyl(script)
        assert result.passed, f"YMYL violations in generated script: {result.violations}"

    def test_different_tickers_return_correct_ticker(self, client: TestClient):
        for ticker in ["9984", "6758", "4502"]:
            payload = _valid_payload()
            payload["ticker"] = ticker
            resp = client.post("/v1/scripts", json=payload)
            assert resp.status_code == 200
            assert resp.json()["ticker"] == ticker
