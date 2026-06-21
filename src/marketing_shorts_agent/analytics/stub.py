"""Analytics stub — returns mock metrics, logs push instead of calling API."""

from __future__ import annotations

import logging

from .interface import AnalyticsInterface, VideoMetrics

logger = logging.getLogger(__name__)


class AnalyticsStub(AnalyticsInterface):
    """Stub analytics implementation for local dev and tests.

    TODO (wave 2): Implement pull() with YouTube Analytics API v2.
    TODO (wave 2): Implement push() with httpx POST to agentops-platform.
    """

    def pull(self, video_id: str) -> VideoMetrics:
        logger.info("[STUB] Pulling analytics for %s", video_id)
        return VideoMetrics(
            video_id=video_id,
            views=0,
            average_view_duration_sec=0.0,
            retention_rate=0.0,
            likes=0,
        )

    def push(self, metrics: VideoMetrics, agent_id: str) -> None:
        logger.info(
            "[STUB] Would push metrics to agentops-platform",
            extra={"agent_id": agent_id, "video_id": metrics.video_id, "views": metrics.views},
        )
