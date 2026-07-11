"""Abstract interface and data models for the video QA stage.

The video QA stage runs after render and before publish.  It is two-layered:

1. Deterministic checks (no LLM) — ffprobe stream detection, duration validation,
   black/white frame detection via pixel statistics on extracted frames.
2. Visual LLM judgment — sampled frames passed to a multimodal model for a
   structured rubric evaluation (text legibility, layout, readability).

Gate behaviour: fail-closed.  Any failure (including QA infrastructure errors)
prevents the publish stage from running.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class QaVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"  # QA infrastructure error — treated as fail (fail-closed)


@dataclass
class DeterministicCheckResult:
    """Result of a single deterministic (non-LLM) check."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class VisualCheckResult:
    """Result of the LLM-based visual rubric check."""

    passed: bool
    reason: str = ""
    rubric_scores: dict[str, float] = field(default_factory=dict)
    """Per-criterion score 0.0-1.0 returned by the LLM, e.g.
    {"text_legibility": 1.0, "layout": 0.8, "readability": 0.9}"""


@dataclass
class QaResult:
    """Aggregated result of the video QA stage."""

    verdict: QaVerdict
    deterministic_checks: list[DeterministicCheckResult] = field(default_factory=list)
    visual_check: VisualCheckResult | None = None
    error: str = ""
    """Non-empty only when verdict == ERROR."""

    @property
    def passed(self) -> bool:
        return self.verdict == QaVerdict.PASS

    def to_metrics(self) -> dict[str, float]:
        """Return a flat dict of metric name → numeric value for agentops push.

        Metric names follow the pattern ``video_qa_*``.
        """
        metrics: dict[str, float] = {
            "video_qa_pass": 1.0 if self.passed else 0.0,
        }
        for check in self.deterministic_checks:
            safe_name = check.name.replace(" ", "_").replace("-", "_").lower()
            metrics[f"video_qa_{safe_name}"] = 1.0 if check.passed else 0.0
        if self.visual_check is not None:
            metrics["video_qa_visual_pass"] = 1.0 if self.visual_check.passed else 0.0
            for criterion, score in self.visual_check.rubric_scores.items():
                safe = criterion.replace(" ", "_").replace("-", "_").lower()
                metrics[f"video_qa_visual_{safe}"] = float(score)
        return metrics


class VideoQAInterface(ABC):
    """Run quality checks on a rendered video file.

    Implementations must be fail-closed: any unhandled exception should be
    caught at the call site and treated as a QaVerdict.ERROR.
    """

    @abstractmethod
    def run(self, video_path: str, expected_duration_sec: float | None = None) -> QaResult:
        """Execute QA checks on the video at *video_path*.

        Args:
            video_path: Local file path or ``file://`` / ``stub://`` URL
                returned by the renderer.  Implementations must handle the
                stub:// scheme gracefully (no real file to inspect).
            expected_duration_sec: When provided, the deterministic duration
                check validates the video length is within ±20 % of this value.

        Returns:
            QaResult with verdict, individual check results, and optional
            visual check details.
        """
        ...
