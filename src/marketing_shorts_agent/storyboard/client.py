"""HTTP client for the storyboard service contract (api/storyboard.openapi.yaml v1.0.0).

The storyboard service URL is read from config via STORYBOARD_URL.  When empty,
the pipeline uses storyboard-stub (started in-process or as a sidecar).
"""

from __future__ import annotations

import logging

import httpx

from ..models import (
    ClipIntent,
    ClipKind,
    Overlay,
    OverlayKind,
    Scene,
    Script,
    Shot,
    ShotType,
    Storyboard,
)
from .interface import StoryboardGeneratorInterface

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 60.0


class StoryboardClientError(RuntimeError):
    """Raised when the storyboard service returns an unexpected response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"Storyboard service error {status_code} [{code}]: {message}")


class StoryboardServiceClient(StoryboardGeneratorInterface):
    """HTTP client for the storyboard service contract.

    Implements StoryboardGeneratorInterface so it can be used as a drop-in
    replacement for in-process generators in PipelineOrchestrator.

    Usage::

        client = StoryboardServiceClient(base_url="https://storyboard.run.app/v1")
        storyboard = client.generate(script)
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self._client = httpx.Client(base_url=self._base_url, headers=headers, timeout=timeout)

    # ── StoryboardGeneratorInterface ─────────────────────────────────────────

    def generate(self, script: Script) -> Storyboard:
        """POST /storyboards — convert a Script to a Storyboard.

        Raises StoryboardClientError on 4xx/5xx.
        """
        payload = _script_to_wire(script)

        logger.info(
            "Requesting storyboard from storyboard service",
            extra={"ticker": script.ticker},
        )
        response = self._client.post("/storyboards", json=payload)

        if response.status_code == 400:
            err = response.json()
            detail = err.get("detail", err)
            if isinstance(detail, dict):
                raise StoryboardClientError(
                    400,
                    detail.get("code", "INVALID"),
                    detail.get("message", ""),
                )
            raise StoryboardClientError(400, "INVALID", str(detail))

        response.raise_for_status()
        return _wire_to_storyboard(response.json())

    # ── Resource management ─────────────────────────────────────────────────

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "StoryboardServiceClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── Wire-format serialisation / deserialisation ───────────────────────────────


def _script_to_wire(script: Script) -> dict:
    """Serialise a Script to the storyboard service wire format."""

    def _seg_to_wire(seg: object) -> dict:
        from ..models import ScriptSegment

        assert isinstance(seg, ScriptSegment)
        out: dict = {"type": seg.type.value, "text": seg.text}
        if seg.figures:
            out["figures"] = [{"label": f.label, "value": f.value} for f in seg.figures]
        if seg.duration_sec is not None:
            out["duration_sec"] = seg.duration_sec
        return out

    return {
        "ticker": script.ticker,
        "title": script.title,
        "segments": [_seg_to_wire(s) for s in script.segments],
    }


def _wire_to_storyboard(data: dict) -> Storyboard:
    """Deserialise the storyboard service wire format into a Storyboard domain model."""

    def _parse_overlay(o: dict) -> Overlay:
        return Overlay(
            kind=OverlayKind(o["kind"]),
            text=o.get("text"),
            label=o.get("label"),
            value=o.get("value"),
        )

    def _parse_clip(c: dict | None) -> ClipIntent | None:
        if c is None:
            return None
        return ClipIntent(
            kind=ClipKind(c["kind"]),
            color=c.get("color"),
            prompt=c.get("prompt"),
            query=c.get("query"),
        )

    def _parse_shot(s: dict) -> Shot:
        return Shot(
            id=s["id"],
            type=ShotType(s["type"]),
            duration_sec=s.get("durationSec"),
            clip=_parse_clip(s.get("clip")),
            overlays=[_parse_overlay(o) for o in s.get("overlays", [])],
        )

    def _parse_scene(sc: dict) -> Scene:
        return Scene(
            id=sc["id"],
            duration_sec=sc.get("durationSec"),
            shots=[_parse_shot(sh) for sh in sc["shots"]],
        )

    return Storyboard(
        title=data["title"],
        ticker=data["ticker"],
        scenes=[_parse_scene(sc) for sc in data["scenes"]],
    )
