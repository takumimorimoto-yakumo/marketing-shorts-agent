"""Abstract analytics interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VideoMetrics:
    video_id: str
    views: int = 0
    average_view_duration_sec: float = 0.0
    retention_rate: float = 0.0
    likes: int = 0
    extra: dict = field(default_factory=dict)


class AnalyticsInterface(ABC):
    """Pull YouTube Analytics and push to agentops-platform /metrics."""

    @abstractmethod
    def pull(self, video_id: str) -> VideoMetrics:
        """Fetch current analytics for the given video."""
        ...

    @abstractmethod
    def push(self, metrics: VideoMetrics, agent_id: str) -> None:
        """POST metrics to agentops-platform /agents/{agent_id}/metrics."""
        ...
