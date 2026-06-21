"""Abstract interface for storyboard generators."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Script, Storyboard


class StoryboardGeneratorInterface(ABC):
    """Convert a Script into a Storyboard (renderer contract input).

    The pipeline calls ``generate(script)`` after YMYL guard passes on the
    Script.  The returned Storyboard must also pass YMYL guard (has_disclaimer).
    """

    @abstractmethod
    def generate(self, script: Script) -> Storyboard:
        """Convert a Script to a Storyboard.

        The returned Storyboard MUST contain at least one Shot with
        type=disclaimer.  YMYL guard is re-run by the pipeline after this call.
        """
        ...
