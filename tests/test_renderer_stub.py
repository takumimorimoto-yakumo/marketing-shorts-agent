"""Tests for renderer-stub contract compliance."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marketing_shorts_agent.models import (
    Overlay,
    OverlayKind,
    Scene,
    Shot,
    ShotType,
    Storyboard,
)


def _storyboard_payload(storyboard: Storyboard) -> dict:
    """Convert Storyboard to the wire format expected by the renderer."""
    return {
        "storyboard": {
            "title": storyboard.title,
            "ticker": storyboard.ticker,
            "scenes": [
                {
                    "id": scene.id,
                    "durationSec": scene.duration_sec,
                    "shots": [
                        {
                            "id": shot.id,
                            "type": shot.type.value,
                            "durationSec": shot.duration_sec,
                            "overlays": [
                                {
                                    "kind": o.kind.value,
                                    "text": o.text,
                                    "label": o.label,
                                    "value": o.value,
                                }
                                for o in shot.overlays
                            ],
                        }
                        for shot in scene.shots
                    ],
                }
                for scene in storyboard.scenes
            ],
        }
    }


class TestRendererStubContractCompliance:
    """Conformance tests: these same assertions will be reused for ffmpeg/Remotion adapters."""

    def test_valid_request_returns_202(self, stub_client: TestClient, valid_storyboard: Storyboard):
        """A valid storyboard with disclaimer → 202 + render id."""
        resp = stub_client.post("/v1/renders", json=_storyboard_payload(valid_storyboard))
        assert resp.status_code == 202
        body = resp.json()
        assert "renderId" in body
        assert body["state"] in ("queued", "rendering", "done")

    def test_missing_disclaimer_returns_400(
        self, stub_client: TestClient, storyboard_without_disclaimer: Storyboard
    ):
        """A storyboard without disclaimer shot → 400 MISSING_DISCLAIMER."""
        resp = stub_client.post(
            "/v1/renders", json=_storyboard_payload(storyboard_without_disclaimer)
        )
        assert resp.status_code == 400
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "MISSING_DISCLAIMER"

    def test_poll_returns_job(self, stub_client: TestClient, valid_storyboard: Storyboard):
        """After submit, GET /renders/{id} returns job state."""
        create_resp = stub_client.post("/v1/renders", json=_storyboard_payload(valid_storyboard))
        assert create_resp.status_code == 202
        render_id = create_resp.json()["renderId"]

        poll_resp = stub_client.get(f"/v1/renders/{render_id}")
        assert poll_resp.status_code == 200
        body = poll_resp.json()
        assert body["renderId"] == render_id
        assert body["state"] in ("queued", "rendering", "done", "failed")

    def test_unknown_render_id_returns_404(self, stub_client: TestClient):
        """GET /renders/{unknown} → 404 NOT_FOUND."""
        resp = stub_client.get("/v1/renders/does-not-exist-xyz")
        assert resp.status_code == 404
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "NOT_FOUND"

    def test_figure_values_reproduced_verbatim(
        self, stub_client: TestClient, valid_storyboard: Storyboard
    ):
        """Figure overlay values MUST appear unaltered in the completed job.

        The stub stores the storyboard; we verify the stored figures in the job
        are identical to what was submitted (immutability contract).
        """
        # Get figure values from the storyboard
        original_figures: list[tuple[str, str]] = []
        for scene in valid_storyboard.scenes:
            for shot in scene.shots:
                for overlay in shot.overlays:
                    if overlay.kind == OverlayKind.FIGURE:
                        original_figures.append((overlay.label or "", overlay.value or ""))

        assert original_figures, "Test setup: storyboard must have figure overlays"

        resp = stub_client.post("/v1/renders", json=_storyboard_payload(valid_storyboard))
        assert resp.status_code == 202
        render_id = resp.json()["renderId"]

        # The stub processes synchronously; job is done immediately
        poll = stub_client.get(f"/v1/renders/{render_id}")
        assert poll.status_code == 200
        job = poll.json()
        assert job["state"] == "done"

        # Retrieve stored storyboard figures from the stub's internal state
        # We verify by re-examining what was submitted (since stub is in-process,
        # we can inspect the app's job store directly)
        from renderer_stub.app import _jobs

        stored = _jobs[render_id]["_storyboard"]
        stored_figures: list[tuple[str, str]] = []
        for scene in stored["scenes"]:
            for shot in scene["shots"]:
                for overlay in shot["overlays"]:
                    if overlay.get("kind") == "figure":
                        stored_figures.append(
                            (overlay.get("label", ""), overlay.get("value", ""))
                        )

        assert stored_figures == original_figures, (
            f"Figure values were altered: expected {original_figures}, got {stored_figures}"
        )
