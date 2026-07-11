"""Video QA stage — deterministic ffprobe checks + Gemini visual judgment.

Public surface:
  VideoQAInterface  — abstract base class
  VideoQAStub       — stub (always passes, no external dependencies)
  VideoQAClient     — real implementation (ffprobe + Gemini multimodal)
  QaResult          — aggregated result dataclass
  QaVerdict         — PASS / FAIL / ERROR enum
"""

from .client import VideoQAClient
from .interface import (
    DeterministicCheckResult,
    QaResult,
    QaVerdict,
    VideoQAInterface,
    VisualCheckResult,
)
from .stub import VideoQAStub

__all__ = [
    "VideoQAInterface",
    "VideoQAStub",
    "VideoQAClient",
    "QaResult",
    "QaVerdict",
    "DeterministicCheckResult",
    "VisualCheckResult",
]
