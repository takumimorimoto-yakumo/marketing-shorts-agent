"""Abstract publisher interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Storyboard


@dataclass
class PublishResult:
    video_id: str
    url: str
    dry_run: bool = False


class PublisherInterface(ABC):
    """Upload a rendered video to YouTube with AI disclosure."""

    @abstractmethod
    def publish(
        self,
        video_path: str,
        storyboard: Storyboard,
        *,
        dry_run: bool = True,
    ) -> PublishResult:
        """Upload video to YouTube Shorts.

        When dry_run=True, no actual upload is performed; returns a mock result.
        AI-generated content disclosure MUST always be set in the upload metadata.
        """
        ...
