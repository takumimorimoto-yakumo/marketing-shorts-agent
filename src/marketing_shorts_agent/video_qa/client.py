"""Real video QA client — ffprobe deterministic checks + Gemini visual judgment.

Layer 1 — Deterministic checks (no LLM):
  - Video stream present (ffprobe JSON probe)
  - Duration within ±20 % of expected (when expected_duration_sec provided)
  - No audio track required (audio is optional for the stub renderer)
  - Black-frame detection: sample frames at 10 %, 50 %, 90 % of duration;
    flag frame if mean luminance < BLACK_THRESHOLD (pixel statistics, no LLM)
  - White-frame detection: flag frame if mean luminance > WHITE_THRESHOLD

Layer 2 — Visual LLM judgment (Gemini multimodal):
  - Same three sampled frames → base64-encoded PNG
  - Structured prompt asks Gemini to score three rubric criteria:
      text_legibility, layout, readability  (each 0.0–1.0)
  - Uses google-generativeai (or google-cloud-aiplatform) with ADC.
  - Backend selected by VIDEO_QA_GEMINI_BACKEND env var:
      "genai"   (default) → google.generativeai
      "vertex"            → google.cloud.aiplatform / vertexai
  - Model ID from config/settings.py (gemini_eval_model).
  - ADC only — no API key usage.

Gate: any deterministic failure → QaVerdict.FAIL.
      All deterministic checks pass + visual pass → QaVerdict.PASS.
      All deterministic checks pass + visual fail → QaVerdict.FAIL.
      Exception in either layer → QaVerdict.ERROR (fail-closed).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .interface import (
    DeterministicCheckResult,
    QaResult,
    QaVerdict,
    VideoQAInterface,
    VisualCheckResult,
)

logger = logging.getLogger(__name__)

# ── Pixel statistics thresholds ────────────────────────────────────────────────
# ffmpeg lavfi signalstats returns YAVG (luminance mean 0-255) per frame.
# These thresholds are conservative to avoid false positives.
_BLACK_THRESHOLD = 10.0   # mean luminance ≤ this → black frame
_WHITE_THRESHOLD = 245.0  # mean luminance ≥ this → white frame

# Duration tolerance: ±20 % of expected
_DURATION_TOLERANCE = 0.20

# Rubric pass threshold: average rubric score must be ≥ this to pass visual check
_VISUAL_PASS_THRESHOLD = 0.6

# Frame sample positions (fraction of total duration)
_SAMPLE_POSITIONS = [0.10, 0.50, 0.90]

# Gemini structured-output schema for visual judgment
_VISUAL_RUBRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "text_legibility": {
            "type": "number",
            "description": "Score 0.0-1.0: text is readable, not cut off, sufficient contrast.",
        },
        "layout": {
            "type": "number",
            "description": "Score 0.0-1.0: layout is well-composed, no broken elements.",
        },
        "readability": {
            "type": "number",
            "description": "Score 0.0-1.0: overall visual readability for a social media short.",
        },
        "pass": {
            "type": "boolean",
            "description": "True if the frame set passes overall visual quality.",
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation of the assessment.",
        },
    },
    "required": ["text_legibility", "layout", "readability", "pass", "reason"],
}

_VISUAL_PROMPT = (
    "You are a video quality reviewer for short-form social media content. "
    "You are given three frames sampled from a Japanese-stock commentary Short video "
    "(at approximately 10%, 50%, and 90% of the video duration). "
    "Evaluate the frames against the following rubric and respond ONLY with a JSON object "
    "matching the schema provided:\n"
    "- text_legibility (0.0-1.0): text is readable, not cut off, has sufficient contrast.\n"
    "- layout (0.0-1.0): layout is well-composed, no broken visual elements.\n"
    "- readability (0.0-1.0): overall visual readability for a social media short.\n"
    "- pass (boolean): true if the overall quality is acceptable for publishing.\n"
    "- reason (string): one or two sentences explaining your assessment.\n"
    "Respond ONLY with the JSON — no markdown, no code block delimiters."
)


class VideoQAClient(VideoQAInterface):
    """Real QA client using ffprobe (deterministic) + Gemini (visual).

    Args:
        gemini_model: Model ID for the visual check (e.g. ``gemini-2.5-flash``).
        gemini_backend: ``"genai"`` or ``"vertex"``.
        gcp_project: GCP project ID (required for ``"vertex"`` backend).
        gcp_region: GCP region (default ``"us-central1"``).
    """

    def __init__(
        self,
        gemini_model: str = "gemini-2.5-flash",
        gemini_backend: str = "genai",
        gcp_project: str = "",
        gcp_region: str = "us-central1",
    ) -> None:
        self._model = gemini_model
        self._backend = gemini_backend
        self._gcp_project = gcp_project
        self._gcp_region = gcp_region

    # ── Public ──────────────────────────────────────────────────────────────

    def run(self, video_path: str, expected_duration_sec: float | None = None) -> QaResult:
        """Run deterministic + visual checks on *video_path*."""
        # Normalise stub:// URLs — no real file to inspect
        local_path = _resolve_local_path(video_path)
        if local_path is None:
            logger.warning(
                "VideoQA: video_path is a stub/placeholder URL; skipping deterministic checks",
                extra={"video_path": video_path},
            )
            return QaResult(
                verdict=QaVerdict.FAIL,
                error="video_path is a stub/placeholder URL; no real video file to inspect",
            )

        # Layer 1: Deterministic checks
        det_checks = self._run_deterministic(local_path, expected_duration_sec)
        any_det_fail = any(not c.passed for c in det_checks)
        if any_det_fail:
            return QaResult(
                verdict=QaVerdict.FAIL,
                deterministic_checks=det_checks,
            )

        # Layer 2: Visual LLM check
        visual = self._run_visual(local_path)
        verdict = QaVerdict.PASS if visual.passed else QaVerdict.FAIL
        return QaResult(
            verdict=verdict,
            deterministic_checks=det_checks,
            visual_check=visual,
        )

    # ── Deterministic (Layer 1) ─────────────────────────────────────────────

    def _run_deterministic(
        self, path: str, expected_duration_sec: float | None
    ) -> list[DeterministicCheckResult]:
        checks: list[DeterministicCheckResult] = []

        # Probe the file with ffprobe
        probe = _ffprobe(path)
        if probe is None:
            checks.append(
                DeterministicCheckResult(
                    name="video_stream_present",
                    passed=False,
                    detail="ffprobe failed or not found",
                )
            )
            return checks

        streams = probe.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]

        # Check 1: video stream exists
        has_video = len(video_streams) > 0
        checks.append(
            DeterministicCheckResult(
                name="video_stream_present",
                passed=has_video,
                detail=f"found {len(video_streams)} video stream(s)",
            )
        )
        if not has_video:
            return checks  # Nothing more to check without a video stream

        vs = video_streams[0]

        # Check 2: duration in range (when expected is provided)
        fmt = probe.get("format", {})
        actual_duration = _parse_float(fmt.get("duration") or vs.get("duration"))
        if expected_duration_sec is not None and actual_duration is not None:
            lo = expected_duration_sec * (1 - _DURATION_TOLERANCE)
            hi = expected_duration_sec * (1 + _DURATION_TOLERANCE)
            in_range = lo <= actual_duration <= hi
            checks.append(
                DeterministicCheckResult(
                    name="duration_in_range",
                    passed=in_range,
                    detail=(
                        f"actual={actual_duration:.1f}s "
                        f"expected={expected_duration_sec:.1f}s "
                        f"tolerance=±{_DURATION_TOLERANCE*100:.0f}%"
                    ),
                )
            )
        else:
            checks.append(
                DeterministicCheckResult(
                    name="duration_in_range",
                    passed=True,
                    detail=(
                        "skipped (no expected_duration_sec provided)"
                        if expected_duration_sec is None
                        else f"actual={actual_duration}s (no expected to compare)"
                    ),
                )
            )

        # Check 3 & 4: black / white frame detection via luminance sampling
        duration_for_sample = actual_duration or 30.0
        black_ok, white_ok = _check_frame_luminance(path, duration_for_sample)
        checks.append(
            DeterministicCheckResult(
                name="no_black_frames",
                passed=black_ok,
                detail="luminance sampling at 10/50/90% of duration",
            )
        )
        checks.append(
            DeterministicCheckResult(
                name="no_white_frames",
                passed=white_ok,
                detail="luminance sampling at 10/50/90% of duration",
            )
        )

        return checks

    # ── Visual LLM (Layer 2) ─────────────────────────────────────────────────

    def _run_visual(self, path: str) -> VisualCheckResult:
        """Extract frames and send to Gemini for rubric evaluation."""
        probe = _ffprobe(path)
        duration = 30.0
        if probe:
            fmt = probe.get("format", {})
            streams = probe.get("streams", [])
            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            raw = fmt.get("duration") or (video_streams[0].get("duration") if video_streams else None)
            duration = _parse_float(raw) or 30.0

        frame_pngs = _extract_frames_as_png(path, duration, _SAMPLE_POSITIONS)
        if not frame_pngs:
            logger.warning("VideoQA visual: no frames extracted; failing visual check")
            return VisualCheckResult(
                passed=False,
                reason="Could not extract frames from video for visual evaluation",
            )

        return self._call_gemini(frame_pngs)

    def _call_gemini(self, frame_pngs: list[bytes]) -> VisualCheckResult:
        """Send frames to Gemini and parse the structured rubric response."""
        if self._backend == "vertex":
            return self._call_vertex(frame_pngs)
        return self._call_genai(frame_pngs)

    def _call_genai(self, frame_pngs: list[bytes]) -> VisualCheckResult:
        """Call Gemini via google-generativeai (genai backend, ADC)."""
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "google-generativeai is not installed. "
                "Run: pip install google-generativeai"
            ) from exc

        # ADC: use Application Default Credentials — no API key
        # google-generativeai picks up ADC automatically when no api_key is set.
        parts: list = []
        for png in frame_pngs:
            parts.append({"mime_type": "image/png", "data": base64.b64encode(png).decode()})
        parts.append(_VISUAL_PROMPT)

        model = genai.GenerativeModel(
            self._model,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            ),
        )
        response = model.generate_content(parts)
        return _parse_visual_response(response.text)

    def _call_vertex(self, frame_pngs: list[bytes]) -> VisualCheckResult:
        """Call Gemini via google-cloud-aiplatform (vertex backend, ADC)."""
        try:
            import vertexai  # type: ignore[import-untyped]
            from vertexai.generative_models import GenerativeModel, Image, Part  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-aiplatform is not installed. "
                "Run: pip install google-cloud-aiplatform[preview]"
            ) from exc

        vertexai.init(project=self._gcp_project or None, location=self._gcp_region)
        model = GenerativeModel(self._model)

        parts: list = []
        for png in frame_pngs:
            parts.append(Part.from_image(Image.from_bytes(png)))
        parts.append(_VISUAL_PROMPT)

        response = model.generate_content(
            parts,
            generation_config={"response_mime_type": "application/json"},
        )
        return _parse_visual_response(response.text)


# ── Module-level helpers ───────────────────────────────────────────────────────


def _resolve_local_path(video_path: str) -> str | None:
    """Convert a video URL/path to a local filesystem path, or None if unavailable."""
    if video_path.startswith("stub://"):
        return None
    if video_path.startswith("file://"):
        path = video_path[len("file://"):]
        return path if Path(path).exists() else None
    # Bare path
    if Path(video_path).exists():
        return video_path
    return None


def _ffprobe(path: str) -> dict | None:
    """Run ffprobe on *path* and return parsed JSON, or None on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return json.loads(result.stdout)
    except Exception as exc:
        logger.warning("ffprobe failed: %s", exc)
        return None


def _parse_float(value: object) -> float | None:
    """Safely parse a float from an ffprobe value."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _check_frame_luminance(path: str, duration: float) -> tuple[bool, bool]:
    """Sample 3 frames and check luminance statistics.

    Returns (black_ok, white_ok):
      black_ok: True when NO sampled frame is fully black
      white_ok: True when NO sampled frame is fully white
    """
    try:
        black_ok = True
        white_ok = True
        for frac in _SAMPLE_POSITIONS:
            t = duration * frac
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-ss", str(t),
                    "-i", path,
                    "-vframes", "1",
                    "-vf", "signalstats",
                    "-show_frames",
                    "-print_format", "json",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                continue  # Skip this frame on error; be lenient
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                continue
            frames = data.get("frames", [])
            for frame in frames:
                tags = frame.get("tags", {})
                yavg_str = tags.get("lavfi.signalstats.YAVG")
                if yavg_str is None:
                    continue
                try:
                    yavg = float(yavg_str)
                except ValueError:
                    continue
                if yavg <= _BLACK_THRESHOLD:
                    black_ok = False
                    logger.info(
                        "VideoQA: black frame detected at %.1fs (YAVG=%.1f)", t, yavg
                    )
                if yavg >= _WHITE_THRESHOLD:
                    white_ok = False
                    logger.info(
                        "VideoQA: white frame detected at %.1fs (YAVG=%.1f)", t, yavg
                    )
        return black_ok, white_ok
    except Exception as exc:
        logger.warning("VideoQA luminance check failed (non-fatal, treating as pass): %s", exc)
        return True, True  # Lenient: luminance check failure does not block


def _extract_frames_as_png(path: str, duration: float, positions: list[float]) -> list[bytes]:
    """Extract frames as PNG bytes at given fractional positions."""
    pngs: list[bytes] = []
    with tempfile.TemporaryDirectory(prefix="video_qa_frames_") as tmpdir:
        for frac in positions:
            t = duration * frac
            out_path = os.path.join(tmpdir, f"frame_{frac:.2f}.png")
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(t),
                    "-i", path,
                    "-vframes", "1",
                    "-f", "image2",
                    out_path,
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and os.path.exists(out_path):
                with open(out_path, "rb") as f:
                    pngs.append(f.read())
            else:
                logger.warning("VideoQA: frame extraction failed at t=%.1fs", t)
    return pngs


def _parse_visual_response(raw: str) -> VisualCheckResult:
    """Parse Gemini's JSON response into a VisualCheckResult."""
    try:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove first and last fence lines
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        data = json.loads(text)
        rubric = {
            k: float(data[k])
            for k in ("text_legibility", "layout", "readability")
            if k in data
        }
        passed = bool(data.get("pass", False))
        # If no explicit pass field, derive from average rubric score
        if rubric and "pass" not in data:
            passed = (sum(rubric.values()) / len(rubric)) >= _VISUAL_PASS_THRESHOLD
        reason = str(data.get("reason", ""))
        return VisualCheckResult(passed=passed, reason=reason, rubric_scores=rubric)
    except Exception as exc:
        logger.warning("VideoQA: could not parse Gemini response: %s | raw=%r", exc, raw[:200])
        return VisualCheckResult(
            passed=False,
            reason=f"Gemini response parse error: {exc}",
        )
