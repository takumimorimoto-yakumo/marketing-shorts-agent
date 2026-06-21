"""Domain models shared across the pipeline.

These Pydantic models mirror the OpenAPI storyboard schema (api/renderer.openapi.yaml v1.0.0)
and the upstream Script model.  They are the single source of truth for data shapes
within the Python codebase.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── Script models (upstream of the renderer contract) ────────────────────────


class ScriptShotType(str, Enum):
    HOOK = "hook"
    NARRATION = "narration"
    FIGURES = "figures"
    DISCLAIMER = "disclaimer"


class FigureItem(BaseModel):
    """A single pre-verified financial figure."""

    label: str = Field(description='e.g. "PER", "売上高"')
    value: str = Field(
        description='Pre-formatted exact value, e.g. "12.3x". MUST NOT be altered.'
    )


class ScriptSegment(BaseModel):
    """One segment in a flat script (upstream representation before storyboard conversion)."""

    type: ScriptShotType
    text: str
    figures: list[FigureItem] = Field(default_factory=list)
    duration_sec: float | None = None


class Script(BaseModel):
    """Structured script for one Short video."""

    ticker: str
    title: str
    segments: list[ScriptSegment] = Field(min_length=1)


# ── Storyboard models (renderer contract) ────────────────────────────────────


class ClipKind(str, Enum):
    GENERATIVE = "generative"
    STOCK = "stock"
    SOLID = "solid"


class ClipIntent(BaseModel):
    """Intent for the background clip of a shot."""

    kind: ClipKind
    color: str | None = Field(default=None, description='CSS hex for solid clips, e.g. "#000000"')
    prompt: str | None = Field(default=None, description="Prompt for generative clips.")
    query: str | None = Field(default=None, description="Search query for stock clips.")


class OverlayKind(str, Enum):
    TEXT = "text"
    FIGURE = "figure"


class Overlay(BaseModel):
    """Visual element layered on top of a clip."""

    kind: OverlayKind
    # text overlays
    text: str | None = None
    # figure overlays — value MUST be reproduced verbatim by renderer
    label: str | None = None
    value: str | None = None


class ShotType(str, Enum):
    HOOK = "hook"
    NARRATION = "narration"
    FIGURES = "figures"
    DISCLAIMER = "disclaimer"


class Shot(BaseModel):
    """Atomic rendering unit."""

    id: str
    type: ShotType
    duration_sec: float | None = None
    clip: ClipIntent | None = None
    overlays: list[Overlay] = Field(default_factory=list)


class Scene(BaseModel):
    """Thematic unit within a Storyboard."""

    id: str
    duration_sec: float | None = None
    shots: list[Shot] = Field(min_length=1)


class Storyboard(BaseModel):
    """Top-level rendering unit — one Short video.

    Contract invariant: at least one Shot with type=disclaimer MUST exist.
    The renderer enforces this; the pipeline should also validate before sending.
    """

    title: str
    ticker: str
    scenes: list[Scene] = Field(min_length=1)

    def has_disclaimer(self) -> bool:
        """Return True iff at least one shot with type=disclaimer exists."""
        return any(
            shot.type == ShotType.DISCLAIMER
            for scene in self.scenes
            for shot in scene.shots
        )

    def all_figure_overlays(self) -> list[Overlay]:
        """Return all figure overlays across all scenes and shots."""
        return [
            overlay
            for scene in self.scenes
            for shot in scene.shots
            for overlay in shot.overlays
            if overlay.kind == OverlayKind.FIGURE
        ]


# ── Renderer API models ───────────────────────────────────────────────────────


class RenderRequest(BaseModel):
    storyboard: Storyboard
    callback_url: str | None = Field(default=None, alias="callbackUrl")

    model_config = {"populate_by_name": True}


class RenderJobState(str, Enum):
    QUEUED = "queued"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"


class RenderJob(BaseModel):
    render_id: str = Field(alias="renderId")
    state: RenderJobState
    video_url: str | None = Field(default=None, alias="videoUrl")
    duration_sec: float | None = Field(default=None, alias="durationSec")
    error: str | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")

    model_config = {"populate_by_name": True}


class RendererError(BaseModel):
    code: str
    message: str
