"""Video QA stub — deterministic fixed results for tests and CI.

The stub mimics both layers of the real QA:
- Deterministic checks: always pass, with realistic check names.
- Visual check: always pass with fixed rubric scores.

No ffprobe, no ffmpeg, no LLM calls — all results are hard-coded constants so
tests are hermetic and repeatable without any external dependency.

When video_path starts with ``stub://`` or ``file://`` pointing to a
non-existent file the stub returns a pass result without raising.
"""

from __future__ import annotations

import logging

from .interface import (
    DeterministicCheckResult,
    QaResult,
    QaVerdict,
    VideoQAInterface,
    VisualCheckResult,
)

logger = logging.getLogger(__name__)

# Fixed rubric scores returned by the stub visual check.
_STUB_RUBRIC_SCORES = {
    "text_legibility": 1.0,
    "layout": 1.0,
    "readability": 1.0,
}


class VideoQAStub(VideoQAInterface):
    """Stub QA implementation — always passes.

    Used in tests (VIDEO_QA_USE_GEMINI not set or VIDEO_QA_USE_GEMINI=false)
    and in CI pipelines where ffprobe / Gemini credentials are unavailable.
    """

    def run(self, video_path: str, expected_duration_sec: float | None = None) -> QaResult:
        logger.info(
            "[STUB] VideoQA running (always passes)",
            extra={"video_path": video_path},
        )

        deterministic = [
            DeterministicCheckResult(name="video_stream_present", passed=True, detail="stub"),
            DeterministicCheckResult(name="duration_in_range", passed=True, detail="stub"),
            DeterministicCheckResult(name="no_black_frames", passed=True, detail="stub"),
            DeterministicCheckResult(name="no_white_frames", passed=True, detail="stub"),
        ]
        visual = VisualCheckResult(
            passed=True,
            reason="stub visual check — always passes",
            rubric_scores=dict(_STUB_RUBRIC_SCORES),
        )
        return QaResult(
            verdict=QaVerdict.PASS,
            deterministic_checks=deterministic,
            visual_check=visual,
        )
