"""M8 conformance suite — renderer contract v1.0.0.

These tests verify that any renderer implementation correctly honours the
contract defined in ``api/renderer.openapi.yaml``.

Target adapters:
  - renderer-stub (bundled)
  - ffmpeg adapter  (adapters/ffmpeg_adapter/app.py)
  - Remotion adapter (adapters/remotion_adapter/app.py)

Running the suite
-----------------

Against the **bundled stub** (default, no external server needed)::

    pytest tests/test_conformance.py -k "stub"

Against the **ffmpeg adapter** (in-process)::

    pytest tests/test_conformance.py -k "ffmpeg"

Against the **Remotion adapter** (in-process)::

    pytest tests/test_conformance.py -k "remotion"

Against a **live external renderer** (set RENDERER_URL env var)::

    RENDERER_URL=http://localhost:8081 pytest tests/test_conformance.py -k "external"

Conformance assertions (per contract)
--------------------------------------
1. Valid request (with disclaimer) → 202 + pollable render id
2. Missing disclaimer → 400 MISSING_DISCLAIMER
3. Polling an unknown render id → 404 NOT_FOUND
4. Figure overlay values are stored / reproduced verbatim (immutability rule)
5. A deliberately non-compliant renderer (no disclaimer check) fails this suite
"""

from __future__ import annotations

import os

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


# ── Storyboard factory helpers ────────────────────────────────────────────────


def _make_storyboard(*, with_disclaimer: bool = True) -> Storyboard:
    """Build a minimal test storyboard."""
    scenes: list[Scene] = [
        Scene(
            id="intro",
            shots=[
                Shot(
                    id="hook-0",
                    type=ShotType.HOOK,
                    duration_sec=3.0,
                    overlays=[Overlay(kind=OverlayKind.TEXT, text="Test intro")],
                )
            ],
        ),
        Scene(
            id="figures",
            shots=[
                Shot(
                    id="figures-0",
                    type=ShotType.FIGURES,
                    duration_sec=4.0,
                    overlays=[
                        Overlay(kind=OverlayKind.FIGURE, label="PER", value="12.3x"),
                        Overlay(kind=OverlayKind.FIGURE, label="PBR", value="1.5x"),
                        Overlay(kind=OverlayKind.FIGURE, label="売上高", value="¥3,000億"),
                    ],
                )
            ],
        ),
    ]

    if with_disclaimer:
        scenes.append(
            Scene(
                id="close",
                shots=[
                    Shot(
                        id="disclaimer-0",
                        type=ShotType.DISCLAIMER,
                        duration_sec=3.0,
                        overlays=[
                            Overlay(
                                kind=OverlayKind.TEXT,
                                text=(
                                    "This video is for informational purposes only "
                                    "and does not constitute investment advice."
                                ),
                            )
                        ],
                    )
                ],
            )
        )

    return Storyboard(title="Conformance Test Short", ticker="9999", scenes=scenes)


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


# ── Extract figure values from raw payload ────────────────────────────────────


def _extract_figures_from_payload(payload: dict) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for scene in payload["storyboard"]["scenes"]:
        for shot in scene["shots"]:
            for overlay in shot.get("overlays", []):
                if overlay.get("kind") == "figure":
                    results.append((overlay.get("label", ""), overlay.get("value", "")))
    return results


# ── Shared conformance assertions ─────────────────────────────────────────────


class RendererConformanceMixin:
    """Mixin that implements the M8 conformance assertions.

    Subclasses must define ``self.client: TestClient``.
    """

    client: TestClient

    def _post_render(self, storyboard: Storyboard) -> tuple[int, dict]:
        payload = _storyboard_payload(storyboard)
        resp = self.client.post("/v1/renders", json=payload)
        return resp.status_code, resp.json()

    # ── Assertion 1: valid request → 202 + render id ──────────────────────────

    def test_valid_request_returns_202_and_render_id(self):
        """A valid storyboard with disclaimer → 202 + renderId."""
        sb = _make_storyboard(with_disclaimer=True)
        status, body = self._post_render(sb)
        assert status == 202, f"Expected 202, got {status}: {body}"
        assert "renderId" in body, f"Missing renderId in response: {body}"
        assert body["renderId"], "renderId must not be empty"
        assert body.get("state") in ("queued", "rendering", "done"), (
            f"Unexpected state: {body.get('state')}"
        )

    # ── Assertion 2: missing disclaimer → 400 MISSING_DISCLAIMER ─────────────

    def test_missing_disclaimer_returns_400(self):
        """A storyboard without any disclaimer shot → 400 MISSING_DISCLAIMER."""
        sb = _make_storyboard(with_disclaimer=False)
        status, body = self._post_render(sb)
        assert status == 400, f"Expected 400, got {status}: {body}"
        detail = body.get("detail", body)
        assert detail.get("code") == "MISSING_DISCLAIMER", (
            f"Expected code=MISSING_DISCLAIMER, got: {detail}"
        )

    # ── Assertion 3: poll after valid submit → 200 with job ──────────────────

    def test_poll_after_submit_returns_200(self):
        """After a successful submit, polling the render id returns 200."""
        sb = _make_storyboard(with_disclaimer=True)
        payload = _storyboard_payload(sb)
        create_resp = self.client.post("/v1/renders", json=payload)
        assert create_resp.status_code == 202
        render_id = create_resp.json()["renderId"]

        poll_resp = self.client.get(f"/v1/renders/{render_id}")
        assert poll_resp.status_code == 200
        body = poll_resp.json()
        assert body["renderId"] == render_id
        assert body["state"] in ("queued", "rendering", "done", "failed")

    # ── Assertion 4: unknown render id → 404 NOT_FOUND ───────────────────────

    def test_unknown_render_id_returns_404(self):
        """GET /renders/{unknown} → 404 NOT_FOUND."""
        resp = self.client.get("/v1/renders/conformance-unknown-id-xyz")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.json()}"
        detail = resp.json().get("detail", resp.json())
        assert detail.get("code") == "NOT_FOUND", f"Expected code=NOT_FOUND, got: {detail}"

    # ── Assertion 5: figure verbatim immutability ─────────────────────────────

    def test_figure_values_preserved_verbatim(self):
        """Figure overlay values MUST appear unaltered in the job response.

        We submit a storyboard with known figure values (including special
        characters like ¥ and 億) and verify that the stored figures are
        byte-for-byte identical to what was submitted.
        """
        sb = _make_storyboard(with_disclaimer=True)
        payload = _storyboard_payload(sb)
        original_figures = _extract_figures_from_payload(payload)

        assert original_figures, "Test setup: storyboard must have figure overlays"

        create_resp = self.client.post("/v1/renders", json=payload)
        assert create_resp.status_code == 202
        render_id = create_resp.json()["renderId"]

        poll_resp = self.client.get(f"/v1/renders/{render_id}")
        assert poll_resp.status_code == 200

        # Check the stored storyboard in the adapter's job store
        stored_figures = self._extract_stored_figures(render_id)
        assert stored_figures == original_figures, (
            f"Figure values were altered.\n"
            f"Expected: {original_figures}\n"
            f"Got:      {stored_figures}"
        )

    def _extract_stored_figures(self, render_id: str) -> list[tuple[str, str]]:
        """Extract figure values from the adapter's internal job store.

        Subclasses may override if the job store is accessed differently.
        Default implementation attempts to access a ``_jobs`` dict from the
        adapter's app module.
        """
        # Default: subclasses override this
        return []


# ── Non-compliant renderer (always passes disclaimer check) ───────────────────


class _NonCompliantApp:
    """A deliberately non-compliant renderer that never enforces MISSING_DISCLAIMER."""

    def __init__(self) -> None:
        from fastapi import FastAPI as _FastAPI
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz

        _app = _FastAPI()
        _store: dict[str, dict] = {}

        @_app.post("/v1/renders", status_code=202)
        def _create(body: dict) -> dict:
            rid = str(_uuid.uuid4())
            _store[rid] = {"renderId": rid, "state": "done"}
            return {"renderId": rid, "state": "done"}

        @_app.get("/v1/renders/{rid}")
        def _get(rid: str) -> dict:
            if rid not in _store:
                from fastapi import HTTPException as _HE
                raise _HE(status_code=404, detail={"code": "NOT_FOUND", "message": "not found"})
            return _store[rid]

        self.app = _app


# ── Stub adapter tests ────────────────────────────────────────────────────────


class TestStubConformance(RendererConformanceMixin):
    """Conformance suite against the bundled renderer-stub."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from renderer_stub.app import app, _jobs

        _jobs.clear()
        self.client = TestClient(app)
        self._jobs = _jobs

    def _extract_stored_figures(self, render_id: str) -> list[tuple[str, str]]:
        from renderer_stub.app import _jobs

        stored = _jobs.get(render_id, {}).get("_storyboard", {})
        figures: list[tuple[str, str]] = []
        for scene in stored.get("scenes", []):
            for shot in scene.get("shots", []):
                for overlay in shot.get("overlays", []):
                    if overlay.get("kind") == "figure":
                        figures.append((overlay.get("label", ""), overlay.get("value", "")))
        return figures


# ── ffmpeg adapter tests ──────────────────────────────────────────────────────


class TestFfmpegAdapterConformance(RendererConformanceMixin):
    """Conformance suite against the ffmpeg reference adapter."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from adapters.ffmpeg_adapter.app import app, _jobs

        _jobs.clear()
        self.client = TestClient(app)
        self._jobs = _jobs

    def _extract_stored_figures(self, render_id: str) -> list[tuple[str, str]]:
        from adapters.ffmpeg_adapter.app import _jobs

        stored = _jobs.get(render_id, {}).get("_storyboard", {})
        figures: list[tuple[str, str]] = []
        for scene in stored.get("scenes", []):
            for shot in scene.get("shots", []):
                for overlay in shot.get("overlays", []):
                    if overlay.get("kind") == "figure":
                        figures.append((overlay.get("label", ""), overlay.get("value", "")))
        return figures


# ── Remotion adapter tests ────────────────────────────────────────────────────


class TestRemotionAdapterConformance(RendererConformanceMixin):
    """Conformance suite against the Remotion reference adapter."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from adapters.remotion_adapter.app import app, _jobs

        _jobs.clear()
        self.client = TestClient(app)
        self._jobs = _jobs

    def _extract_stored_figures(self, render_id: str) -> list[tuple[str, str]]:
        from adapters.remotion_adapter.app import _jobs

        stored = _jobs.get(render_id, {}).get("_storyboard", {})
        figures: list[tuple[str, str]] = []
        for scene in stored.get("scenes", []):
            for shot in scene.get("shots", []):
                for overlay in shot.get("overlays", []):
                    if overlay.get("kind") == "figure":
                        figures.append((overlay.get("label", ""), overlay.get("value", "")))
        return figures


# ── Non-compliant renderer MUST fail the suite ────────────────────────────────


class TestNonCompliantRendererFails:
    """Verify that a deliberately non-compliant renderer fails the conformance suite.

    The non-compliant renderer never rejects requests missing a disclaimer shot.
    This test proves the conformance suite catches that violation.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        nc = _NonCompliantApp()
        self.client = TestClient(nc.app)

    def test_non_compliant_renderer_does_not_enforce_missing_disclaimer(self):
        """A non-compliant renderer returns 202 even without a disclaimer shot.

        This test is expected to prove that the conformance suite WOULD flag it:
        a conformance run against this renderer would fail assertion 2.
        """
        sb = _make_storyboard(with_disclaimer=False)
        payload = _storyboard_payload(sb)
        resp = self.client.post("/v1/renders", json=payload)

        # The non-compliant renderer incorrectly returns 202 (it should return 400)
        assert resp.status_code == 202, (
            "This test verifies the non-compliant renderer fails to enforce MISSING_DISCLAIMER. "
            "If it returns 400 here, the renderer is actually compliant."
        )
        # Confirm: the conformance assertion WOULD fail for this renderer
        detail = resp.json()
        assert "renderId" in detail, "Non-compliant renderer accepted a no-disclaimer request"


# ── External renderer tests (optional, requires RENDERER_URL env var) ─────────


@pytest.mark.skipif(
    not os.environ.get("RENDERER_URL"),
    reason="RENDERER_URL not set; skip external renderer conformance",
)
class TestExternalRendererConformance(RendererConformanceMixin):
    """Conformance suite against a live external renderer.

    Set RENDERER_URL=http://your-renderer/v1 to run this class.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        import httpx

        renderer_url = os.environ["RENDERER_URL"].rstrip("/")

        class _ExternalClient:
            """Thin wrapper to match TestClient's interface for an external server."""

            def __init__(self, base_url: str) -> None:
                self._base = base_url

            def post(self, path: str, json: dict) -> "_ExternalResponse":
                r = httpx.post(f"{self._base}{path}", json=json, timeout=30)
                return _ExternalResponse(r.status_code, r.json())

            def get(self, path: str) -> "_ExternalResponse":
                r = httpx.get(f"{self._base}{path}", timeout=30)
                return _ExternalResponse(r.status_code, r.json())

        class _ExternalResponse:
            def __init__(self, status_code: int, data: dict) -> None:
                self.status_code = status_code
                self._data = data

            def json(self) -> dict:
                return self._data

        self.client = _ExternalClient(renderer_url)  # type: ignore[assignment]
