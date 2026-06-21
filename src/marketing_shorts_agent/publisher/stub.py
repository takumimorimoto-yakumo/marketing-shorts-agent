"""Dry-run publisher stub — logs what it would upload, does not call YouTube API."""

from __future__ import annotations

import logging
import uuid

from ..models import Storyboard
from .interface import PublishResult, PublisherInterface

logger = logging.getLogger(__name__)


class DryRunPublisher(PublisherInterface):
    """Publisher stub.  Always operates in dry-run mode.

    A production implementation (not in this repo) would call the YouTube
    Data API v3 with ``madeForKids=false`` and AI-disclosure metadata set.
    """

    def publish(
        self,
        video_path: str,
        storyboard: Storyboard,
        *,
        dry_run: bool = True,
    ) -> PublishResult:
        video_id = f"stub-{uuid.uuid4().hex[:8]}"
        url = f"https://www.youtube.com/shorts/{video_id}"

        logger.info(
            "[DRY-RUN] Would upload to YouTube Shorts",
            extra={
                "video_path": video_path,
                "ticker": storyboard.ticker,
                "title": storyboard.title,
                "video_id": video_id,
                "ai_disclosure": True,  # Always required
            },
        )
        return PublishResult(video_id=video_id, url=url, dry_run=True)
