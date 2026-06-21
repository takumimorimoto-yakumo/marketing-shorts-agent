"""Publisher — YouTube Shorts upload (dry-run / stub)."""

from .interface import PublisherInterface, PublishResult
from .stub import DryRunPublisher

__all__ = ["PublisherInterface", "PublishResult", "DryRunPublisher"]
