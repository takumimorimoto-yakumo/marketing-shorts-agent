"""Renderer stub — FastAPI service implementing the renderer contract v1.0.0.

Implements:
  POST /v1/renders   — validate storyboard (reject if no disclaimer), queue job
  GET  /v1/renders/{renderId} — return job state

Video output: this stub does NOT produce a real mp4 when ffmpeg is unavailable.
It marks the job as done with a placeholder videoUrl. If ffmpeg IS available on
the PATH, it generates a black background + text overlay mp4.

Contract invariants enforced:
1. MISSING_DISCLAIMER — 400 if no shot with type=disclaimer.
2. Figure immutability — not enforced here (client-side responsibility);
   the conformance suite tests it.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Renderer Stub", version="1.0.0")

_CONTRACT_MAJOR = "1"

# In-memory job store (sufficient for stub; no persistence needed)
_jobs: dict[str, dict] = {}


# ── Request / response models (minimal, schema-aligned) ──────────────────────


class _OverlayIn(BaseModel):
    kind: str
    text: str | None = None
    label: str | None = None
    value: str | None = None


class _ShotIn(BaseModel):
    id: str
    type: str
    durationSec: float | None = None
    clip: dict | None = None
    overlays: list[_OverlayIn] = []


class _SceneIn(BaseModel):
    id: str
    durationSec: float | None = None
    shots: list[_ShotIn]


class _StoryboardIn(BaseModel):
    title: str
    ticker: str
    scenes: list[_SceneIn]


class _RenderRequestIn(BaseModel):
    storyboard: _StoryboardIn
    callbackUrl: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _has_disclaimer(storyboard: _StoryboardIn) -> bool:
    return any(
        shot.type == "disclaimer"
        for scene in storyboard.scenes
        for shot in scene.shots
    )


def _collect_text_lines(storyboard: _StoryboardIn) -> list[str]:
    """Collect ASCII-safe text lines for ffmpeg drawtext.

    ffmpeg drawtext does not handle CJK characters without a CJK font; we
    fall back to ASCII representations for the stub.  Figure labels/values
    are reproduced verbatim (immutability contract) but CJK chars are replaced
    with their Unicode codepoint placeholders to avoid ffmpeg errors.
    """
    def ascii_safe(s: str) -> str:
        return "".join(c if ord(c) < 128 else f"[U+{ord(c):04X}]" for c in s)[:80]

    lines: list[str] = [
        f"Ticker: {storyboard.ticker}",
        ascii_safe(storyboard.title),
    ]
    for scene in storyboard.scenes:
        for shot in scene.shots:
            for overlay in shot.overlays:
                if overlay.kind == "text" and overlay.text:
                    lines.append(ascii_safe(overlay.text))
                elif overlay.kind == "figure" and overlay.label and overlay.value:
                    # Reproduce verbatim — no alteration (contract immutability)
                    lines.append(ascii_safe(f"{overlay.label}: {overlay.value}"))
    return lines


def _total_duration(storyboard: _StoryboardIn) -> float:
    total = sum(
        scene.durationSec or 0.0
        for scene in storyboard.scenes
    )
    return total or 30.0  # default 30s if not specified


def _try_generate_mp4(storyboard: _StoryboardIn) -> str | None:
    """Attempt to create a black+text mp4 using ffmpeg. Returns file path or None.

    Falls back to a plain black video if the drawtext filter is unavailable
    in the local ffmpeg build (e.g. compiled without libfreetype).
    """
    if not shutil.which("ffmpeg"):
        logger.info("ffmpeg not found; skipping real mp4 generation")
        return None

    lines = _collect_text_lines(storyboard)
    duration = min(_total_duration(storyboard), 60.0)

    out_dir = Path(tempfile.mkdtemp(prefix="renderer_stub_"))
    out_path = out_dir / "output.mp4"

    def _run(vf: str) -> bool:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={duration}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-movflags", "+faststart",
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            return True
        except subprocess.CalledProcessError:
            return False

    # Attempt 1: with drawtext overlays
    # Escape order matters: backslash first, then quote, colon, comma.
    # Comma must be escaped because ffmpeg uses it as the filter-chain separator.
    drawtext_parts: list[str] = []
    for i, line in enumerate(lines[:5]):
        safe = (
            line
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace(":", "\\:")
            .replace(",", "\\,")
        )
        y_pos = 50 + i * 60
        drawtext_parts.append(
            f"drawtext=text='{safe}':fontcolor=white:fontsize=28:x=20:y={y_pos}"
        )
    vf_text = ",".join(drawtext_parts) if drawtext_parts else "drawtext=text='stub':fontcolor=white:fontsize=28:x=20:y=50"

    if _run(vf_text):
        logger.info("ffmpeg mp4 generated", extra={"path": str(out_path)})
        return str(out_path)

    # Attempt 2: plain black video (drawtext filter unavailable)
    logger.info("drawtext unavailable; generating plain black mp4 as fallback")
    if _run("null"):
        logger.info("ffmpeg plain mp4 generated", extra={"path": str(out_path)})
        return str(out_path)

    logger.warning("ffmpeg failed to generate mp4 even without overlays")
    return None


# ── Routes ───────────────────────────────────────────────────────────────────


@app.post("/v1/renders", status_code=202)
def create_render(body: _RenderRequestIn, response: Response) -> dict:
    """Submit storyboard for rendering. Returns 202 + job id."""
    response.headers["X-Contract-Version"] = _CONTRACT_MAJOR

    storyboard = body.storyboard

    # Contract enforcement: reject if no disclaimer shot
    if not _has_disclaimer(storyboard):
        raise HTTPException(
            status_code=400,
            detail={"code": "MISSING_DISCLAIMER", "message": "No disclaimer shot found in storyboard."},
        )

    render_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    _jobs[render_id] = {
        "renderId": render_id,
        "state": "queued",
        "createdAt": now,
        "_storyboard": storyboard.model_dump(),
        "_callback_url": body.callbackUrl,
    }

    # Synchronously attempt to render (stub is fast enough for tests)
    _process_job(render_id)

    return {"renderId": render_id, "state": _jobs[render_id]["state"], "createdAt": now}


@app.get("/v1/renders/{render_id}")
def get_render(render_id: str, response: Response) -> dict:
    """Poll render job status."""
    response.headers["X-Contract-Version"] = _CONTRACT_MAJOR

    job = _jobs.get(render_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Render {render_id!r} not found."},
        )
    # Return job dict minus internal keys
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _process_job(render_id: str) -> None:
    """Synchronously move a job from queued → rendering → done."""
    job = _jobs[render_id]
    job["state"] = "rendering"

    storyboard_data = job["_storyboard"]
    # Reconstruct minimal object for mp4 generation
    storyboard = _StoryboardIn(**storyboard_data)

    mp4_path = _try_generate_mp4(storyboard)

    job["state"] = "done"
    job["finishedAt"] = datetime.now(timezone.utc).isoformat()
    job["durationSec"] = min(_total_duration(storyboard), 60.0)

    if mp4_path:
        job["videoUrl"] = f"file://{mp4_path}"
    else:
        # No ffmpeg — return a placeholder URL (contract-compliant: videoUrl is optional until done)
        job["videoUrl"] = f"stub://no-ffmpeg/{render_id}.mp4"
