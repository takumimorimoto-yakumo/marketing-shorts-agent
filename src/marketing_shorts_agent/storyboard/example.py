"""Generic example storyboard generator.

Converts a Script (flat segment list) into a Storyboard (scenes + shots with
clip intents and overlays).  Deterministic, template-based — no LLM call.

Each ScriptSegment type maps to a Scene with one Shot and appropriate overlays.
"""

from __future__ import annotations

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

# Default clip intents per shot type
_SHOT_CLIP_DEFAULTS: dict[ShotType, ClipIntent] = {
    ShotType.HOOK: ClipIntent(kind=ClipKind.GENERATIVE, prompt="Dynamic abstract financial cityscape"),
    ShotType.NARRATION: ClipIntent(kind=ClipKind.STOCK, query="business presentation abstract"),
    ShotType.FIGURES: ClipIntent(kind=ClipKind.SOLID, color="#0a0a1e"),
    ShotType.DISCLAIMER: ClipIntent(kind=ClipKind.SOLID, color="#000000"),
}


class ExampleStoryboardGenerator(StoryboardGeneratorInterface):
    """Template-based storyboard generator (bundled reference implementation).

    Maps each ScriptSegment 1:1 to a Scene containing one Shot.
    Figure segments get figure overlays; disclaimer gets a text overlay with
    the disclaimer text.
    """

    def generate(self, script: Script) -> Storyboard:
        """Convert a Script to a single-shot-per-scene Storyboard."""
        scenes: list[Scene] = []

        for i, segment in enumerate(script.segments):
            shot_type = ShotType(segment.type.value)  # same enum values
            shot_id = f"{shot_type.value}-{i}"
            scene_id = f"scene-{i:02d}-{shot_type.value}"

            overlays: list[Overlay] = []

            if shot_type == ShotType.FIGURES:
                # Add figure overlays — values are immutable contract items
                for fig in segment.figures:
                    overlays.append(
                        Overlay(kind=OverlayKind.FIGURE, label=fig.label, value=fig.value)
                    )
                # Also add narration caption
                overlays.append(Overlay(kind=OverlayKind.TEXT, text=segment.text))

            elif shot_type in (ShotType.DISCLAIMER, ShotType.NARRATION, ShotType.HOOK):
                overlays.append(Overlay(kind=OverlayKind.TEXT, text=segment.text))

            shot = Shot(
                id=shot_id,
                type=shot_type,
                duration_sec=segment.duration_sec,
                clip=_SHOT_CLIP_DEFAULTS[shot_type],
                overlays=overlays,
            )
            scenes.append(Scene(id=scene_id, duration_sec=segment.duration_sec, shots=[shot]))

        return Storyboard(ticker=script.ticker, title=script.title, scenes=scenes)
