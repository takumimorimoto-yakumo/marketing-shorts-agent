"""Storyboard stub — FastAPI service implementing the storyboard contract v1.0.0.

Implements:
  POST /v1/storyboards — validate Script input, delegate to ExampleStoryboardGenerator,
                         return the Storyboard as JSON (same schema as renderer contract).

This stub wraps ExampleStoryboardGenerator (the bundled reference implementation)
so the whole pipeline runs end-to-end without any private dependency.  Any HTTP
service that implements the contract can replace this stub.

Contract invariants enforced:
1. MISSING_DISCLAIMER — 400 if the input Script lacks a disclaimer segment.
2. MISSING_DISCLAIMER — 400 if the generated Storyboard lacks a disclaimer shot.
3. Figure values are passed through verbatim (immutability enforced by
   ExampleStoryboardGenerator, validated before returning).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Storyboard Stub", version="1.0.0")

_CONTRACT_MAJOR = "1"


# ── Request models (Script — aligned with storyboard.openapi.yaml) ────────────


class _FigureItemIn(BaseModel):
    label: str
    value: str


class _SegmentIn(BaseModel):
    type: str
    text: str
    figures: list[_FigureItemIn] = []
    duration_sec: float | None = None


class _ScriptIn(BaseModel):
    ticker: str
    title: str
    segments: list[_SegmentIn]


# ── Route ─────────────────────────────────────────────────────────────────────


@app.post("/v1/storyboards", status_code=200)
def create_storyboard(body: _ScriptIn, response: Response) -> dict[str, Any]:
    """Convert a Script to a Storyboard via ExampleStoryboardGenerator.

    Enforces contract invariants before returning:
    - Input Script must contain a disclaimer segment.
    - Output Storyboard must contain a disclaimer shot.
    - Figure overlay values must match input figures verbatim.
    """
    response.headers["X-Contract-Version"] = _CONTRACT_MAJOR

    # Validate input: disclaimer segment required
    has_disclaimer_segment = any(s.type == "disclaimer" for s in body.segments)
    if not has_disclaimer_segment:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_DISCLAIMER",
                "message": "Input Script does not contain a disclaimer segment.",
            },
        )

    # Convert wire input to domain models
    from marketing_shorts_agent.models import (
        FigureItem,
        Script,
        ScriptSegment,
        ScriptShotType,
    )

    segments = [
        ScriptSegment(
            type=ScriptShotType(seg.type),
            text=seg.text,
            figures=[FigureItem(label=f.label, value=f.value) for f in seg.figures],
            duration_sec=seg.duration_sec,
        )
        for seg in body.segments
    ]
    script = Script(ticker=body.ticker, title=body.title, segments=segments)

    # Generate storyboard
    from marketing_shorts_agent.storyboard.example import ExampleStoryboardGenerator

    generator = ExampleStoryboardGenerator()
    storyboard = generator.generate(script)

    # Enforce output invariant: disclaimer shot required
    if not storyboard.has_disclaimer():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_DISCLAIMER",
                "message": "Generated Storyboard does not contain a disclaimer shot.",
            },
        )

    # Enforce figure immutability: all figure overlays must match input figures verbatim
    input_figures = {
        (f.label, f.value)
        for seg in body.segments
        if seg.type == "figures"
        for f in seg.figures
    }
    output_figures = {
        (o.label, o.value)
        for o in storyboard.all_figure_overlays()
        if o.label is not None and o.value is not None
    }
    altered = output_figures - input_figures
    if altered:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "FIGURE_ALTERED",
                "message": f"Figure overlay values were altered: {altered}",
            },
        )

    return _storyboard_to_wire(storyboard)


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _storyboard_to_wire(storyboard: object) -> dict[str, Any]:
    """Convert a Storyboard model to the JSON wire format (renderer-contract-compatible)."""
    from marketing_shorts_agent.models import Storyboard

    assert isinstance(storyboard, Storyboard)

    def _overlay_to_wire(o: object) -> dict[str, Any]:
        from marketing_shorts_agent.models import Overlay

        assert isinstance(o, Overlay)
        out: dict[str, Any] = {"kind": o.kind.value}
        if o.text is not None:
            out["text"] = o.text
        if o.label is not None:
            out["label"] = o.label
        if o.value is not None:
            out["value"] = o.value
        return out

    def _shot_to_wire(shot: object) -> dict[str, Any]:
        from marketing_shorts_agent.models import Shot

        assert isinstance(shot, Shot)
        out: dict[str, Any] = {"id": shot.id, "type": shot.type.value}
        if shot.duration_sec is not None:
            out["durationSec"] = shot.duration_sec
        if shot.clip is not None:
            clip: dict[str, Any] = {"kind": shot.clip.kind.value}
            if shot.clip.color is not None:
                clip["color"] = shot.clip.color
            if shot.clip.prompt is not None:
                clip["prompt"] = shot.clip.prompt
            if shot.clip.query is not None:
                clip["query"] = shot.clip.query
            out["clip"] = clip
        out["overlays"] = [_overlay_to_wire(o) for o in shot.overlays]
        return out

    def _scene_to_wire(scene: object) -> dict[str, Any]:
        from marketing_shorts_agent.models import Scene

        assert isinstance(scene, Scene)
        out: dict[str, Any] = {"id": scene.id}
        if scene.duration_sec is not None:
            out["durationSec"] = scene.duration_sec
        out["shots"] = [_shot_to_wire(sh) for sh in scene.shots]
        return out

    return {
        "title": storyboard.title,
        "ticker": storyboard.ticker,
        "scenes": [_scene_to_wire(sc) for sc in storyboard.scenes],
    }
