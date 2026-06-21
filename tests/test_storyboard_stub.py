"""Tests for the storyboard-stub service (storyboard.openapi.yaml v1.0.0).

Verifies contract compliance:
1. Valid Script → 200 + Storyboard with disclaimer shot
2. Script without disclaimer → 400 MISSING_DISCLAIMER
3. Figure overlay values reproduced verbatim (immutability rule)
4. Storyboard schema is renderer-contract-compatible (same scene/shot/overlay shape)
5. X-Contract-Version header is set to "1"
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def client() -> TestClient:
    from storyboard_stub.app import app

    return TestClient(app)


def _valid_script_payload(*, with_disclaimer: bool = True) -> dict:
    segments = [
        {"type": "hook", "text": "テスト企業の解説！", "duration_sec": 5.0},
        {
            "type": "figures",
            "text": "主要指標",
            "figures": [
                {"label": "PER", "value": "12.3x"},
                {"label": "PBR", "value": "1.5x"},
                {"label": "売上高", "value": "¥3,000億"},
            ],
            "duration_sec": 15.0,
        },
        {"type": "narration", "text": "詳細はご自身でご確認ください。", "duration_sec": 10.0},
    ]
    if with_disclaimer:
        segments.append(
            {
                "type": "disclaimer",
                "text": "この動画は情報提供のみを目的としており投資推奨ではありません。",
                "duration_sec": 5.0,
            }
        )
    return {"ticker": "7203", "title": "テスト株式会社 解説", "segments": segments}


def _extract_figure_overlays(storyboard: dict) -> list[tuple[str, str]]:
    results = []
    for scene in storyboard.get("scenes", []):
        for shot in scene.get("shots", []):
            for overlay in shot.get("overlays", []):
                if overlay.get("kind") == "figure":
                    results.append((overlay.get("label", ""), overlay.get("value", "")))
    return results


class TestStoryboardStubContract:
    def test_valid_script_returns_200(self, client: TestClient):
        resp = client.post("/v1/storyboards", json=_valid_script_payload())
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_response_has_storyboard_fields(self, client: TestClient):
        resp = client.post("/v1/storyboards", json=_valid_script_payload())
        body = resp.json()
        assert "title" in body
        assert "ticker" in body
        assert "scenes" in body
        assert body["ticker"] == "7203"
        assert len(body["scenes"]) >= 1

    def test_storyboard_contains_disclaimer_shot(self, client: TestClient):
        """Output Storyboard must contain at least one shot with type=disclaimer."""
        resp = client.post("/v1/storyboards", json=_valid_script_payload())
        body = resp.json()
        all_shot_types = [
            shot["type"]
            for scene in body["scenes"]
            for shot in scene["shots"]
        ]
        assert "disclaimer" in all_shot_types, (
            f"No disclaimer shot in storyboard. Shot types: {all_shot_types}"
        )

    def test_missing_disclaimer_returns_400(self, client: TestClient):
        """Script without disclaimer segment → 400 MISSING_DISCLAIMER."""
        payload = _valid_script_payload(with_disclaimer=False)
        resp = client.post("/v1/storyboards", json=payload)
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", resp.json())
        assert detail.get("code") == "MISSING_DISCLAIMER", (
            f"Expected code=MISSING_DISCLAIMER, got: {detail}"
        )

    def test_figure_values_reproduced_verbatim(self, client: TestClient):
        """Figure overlay values in the Storyboard must match the Script's figures verbatim."""
        payload = _valid_script_payload()
        resp = client.post("/v1/storyboards", json=payload)
        assert resp.status_code == 200

        # Extract input figures
        input_figures = {
            (f["label"], f["value"])
            for seg in payload["segments"]
            if seg["type"] == "figures"
            for f in seg.get("figures", [])
        }

        # Extract output figure overlays
        output_figures = set(_extract_figure_overlays(resp.json()))

        missing = input_figures - output_figures
        assert not missing, (
            f"Figure values missing or altered in output storyboard.\n"
            f"Expected: {input_figures}\n"
            f"Got:      {output_figures}"
        )

    def test_shots_have_required_fields(self, client: TestClient):
        """Every Shot in the Storyboard must have 'id' and 'type' fields."""
        resp = client.post("/v1/storyboards", json=_valid_script_payload())
        body = resp.json()
        for scene in body["scenes"]:
            for shot in scene["shots"]:
                assert "id" in shot, f"Shot missing 'id': {shot}"
                assert "type" in shot, f"Shot missing 'type': {shot}"
                assert shot["type"] in ("hook", "narration", "figures", "disclaimer")

    def test_scene_ids_are_stable_strings(self, client: TestClient):
        """Every Scene must have a non-empty 'id' string."""
        resp = client.post("/v1/storyboards", json=_valid_script_payload())
        body = resp.json()
        for scene in body["scenes"]:
            assert "id" in scene and scene["id"], f"Scene missing stable id: {scene}"

    def test_x_contract_version_header(self, client: TestClient):
        resp = client.post("/v1/storyboards", json=_valid_script_payload())
        assert resp.headers.get("x-contract-version") == "1", (
            f"Expected X-Contract-Version: 1, got: {resp.headers.get('x-contract-version')}"
        )

    def test_missing_required_field_returns_422(self, client: TestClient):
        """Omitting a required field triggers FastAPI schema validation → 422."""
        payload = _valid_script_payload()
        del payload["ticker"]
        resp = client.post("/v1/storyboards", json=payload)
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_renderer_contract_compatible_overlay_kinds(self, client: TestClient):
        """All overlays must use kinds defined in the renderer contract: text | figure."""
        resp = client.post("/v1/storyboards", json=_valid_script_payload())
        body = resp.json()
        for scene in body["scenes"]:
            for shot in scene["shots"]:
                for overlay in shot.get("overlays", []):
                    assert overlay["kind"] in ("text", "figure"), (
                        f"Unknown overlay kind: {overlay['kind']}"
                    )
