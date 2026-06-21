"""Abstract version register interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VersionRecord:
    agent_id: str
    version: str
    """Semantic version string, e.g. '1.2.3'."""
    content_generator_class: str
    """Fully-qualified class name of the content generator used."""
    metadata: dict = field(default_factory=dict)


class VersionRegisterInterface(ABC):
    """Register a pipeline version with agentops-platform so it can be canaried."""

    @abstractmethod
    def register(self, record: VersionRecord) -> str:
        """Register a version; return the platform-assigned version id."""
        ...
