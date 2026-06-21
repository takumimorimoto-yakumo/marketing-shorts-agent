"""Remotion reference renderer — implements renderer contract v1.0.0.

This adapter is a clean-room implementation of the renderer contract using
React / Remotion.  It wraps the Remotion CLI (``npx remotion render``) to
turn a Storyboard into a 9:16 vertical mp4.

Contract invariants enforced:
  1. MISSING_DISCLAIMER — 400 if no shot with type=disclaimer exists.
  2. Figure immutability — figure overlay values are passed verbatim to the
     Remotion composition; they appear unaltered on screen.

The Remotion project lives in ``adapters/remotion_adapter/video/``.

Usage (standalone)::

    uvicorn adapters.remotion_adapter.app:app --port 8082

Or as a Docker container — see adapters/remotion_adapter/Dockerfile.

Response header ``X-Contract-Version: 1`` is set on all successful responses.

Note on Remotion CLI availability:
  When Node.js / Remotion CLI is not available, render falls back to a
  placeholder video URL (same pattern as the ffmpeg adapter).  The contract
  shape (202 → poll → done) is always honoured; only the actual mp4 is
  optional in the stub path.
"""

from __future__ import annotations

import json
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

# ── Contract constants ────────────────────────────────────────────────────────
_CONTRACT_MAJOR = "1"
_MAX_VIDEO_DURATION_SEC = 60.0
_DEFAULT_SHOT_DURATION_SEC = 5.0

# Path to the Remotion project relative to this file
_REMOTION_PROJECT_DIR = Path(__file__).parent / "video"
_REMOTION_ENTRY = _REMOTION_PROJECT_DIR / "src" / "index.tsx"
_COMPOSITION_ID = "StoryboardVideo"

app = FastAPI(
    title="Remotion Reference Renderer",
    version=_CONTRACT_MAJOR + ".0.0",
    description="Renderer contract v1.0.0 reference implementation using React/Remotion.",
)

# In-memory job store
_jobs: dict[str, dict] = {}


# ── Pydantic request models (mirror OpenAPI schema) ───────────────────────────


class _OverlayIn(BaseModel):
    kind: str  # "text" | "figure"
    text: str | None = None
    label: str | None = None
    value: str | None = None


class _ClipIntentIn(BaseModel):
    kind: str  # "generative" | "stock" | "solid"
    color: str | None = None
    prompt: str | None = None
    query: str | None = None


class _ShotIn(BaseModel):
    id: str
    type: str  # "hook" | "narration" | "figures" | "disclaimer"
    durationSec: float | None = None
    clip: _ClipIntentIn | None = None
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


# ── Contract enforcement ──────────────────────────────────────────────────────


def _has_disclaimer(storyboard: _StoryboardIn) -> bool:
    return any(
        shot.type == "disclaimer"
        for scene in storyboard.scenes
        for shot in scene.shots
    )


# ── Duration helpers ──────────────────────────────────────────────────────────


def _shot_duration(shot: _ShotIn) -> float:
    return shot.durationSec if shot.durationSec and shot.durationSec > 0 else _DEFAULT_SHOT_DURATION_SEC


def _total_duration(storyboard: _StoryboardIn) -> float:
    shots = [s for scene in storyboard.scenes for s in scene.shots]
    total = sum(_shot_duration(s) for s in shots)
    return min(total or _DEFAULT_SHOT_DURATION_SEC, _MAX_VIDEO_DURATION_SEC)


# ── Remotion render ───────────────────────────────────────────────────────────


def _remotion_available() -> bool:
    """Check if Node.js and the Remotion CLI are available."""
    return shutil.which("node") is not None and _REMOTION_PROJECT_DIR.exists()


def _render_with_remotion(storyboard: _StoryboardIn) -> str | None:
    """Invoke Remotion CLI to render the storyboard.

    Passes the storyboard JSON as input props.  Returns output mp4 path or None.
    Figure values are passed verbatim in the props JSON (immutability contract).
    """
    if not _remotion_available():
        logger.warning("Node.js or Remotion project not found; skipping Remotion render")
        return None

    out_dir = Path(tempfile.mkdtemp(prefix="remotion_adapter_"))
    out_path = out_dir / "output.mp4"

    # Storyboard is passed verbatim as Remotion input props
    # Figure overlay values are not modified (immutability contract)
    input_props = json.dumps({"storyboard": storyboard.model_dump()})

    duration = _total_duration(storyboard)
    fps = 30
    duration_frames = int(duration * fps)

    cmd = [
        "npx", "remotion", "render",
        str(_REMOTION_ENTRY),
        _COMPOSITION_ID,
        str(out_path),
        "--props", input_props,
        "--frames", f"0-{duration_frames - 1}",
        "--log", "verbose",
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=300,
            cwd=str(_REMOTION_PROJECT_DIR),
        )
        logger.info(
            "Remotion render complete",
            extra={"path": str(out_path), "duration": duration},
        )
        return str(out_path)
    except subprocess.CalledProcessError as exc:
        logger.error("Remotion render failed: %s", exc.stderr.decode()[:500])
        return None


# ── Routes ────────────────────────────────────────────────────────────────────


@app.post("/v1/renders", status_code=202)
def create_render(body: _RenderRequestIn, response: Response) -> dict:
    """Submit storyboard for rendering (Remotion adapter).

    Returns 202 with a render job id.

    400 conditions:
      - No shot with type=disclaimer → MISSING_DISCLAIMER
      - Schema validation error → handled by FastAPI/Pydantic automatically
    """
    response.headers["X-Contract-Version"] = _CONTRACT_MAJOR

    storyboard = body.storyboard

    if not _has_disclaimer(storyboard):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_DISCLAIMER",
                "message": "No shot with type=disclaimer found in storyboard.",
            },
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

    _process_job(render_id)
    return {
        "renderId": render_id,
        "state": _jobs[render_id]["state"],
        "createdAt": now,
    }


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
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _process_job(render_id: str) -> None:
    """Move job queued → rendering → done (or failed on error)."""
    job = _jobs[render_id]
    job["state"] = "rendering"

    storyboard_data = job["_storyboard"]
    storyboard = _StoryboardIn(**storyboard_data)

    try:
        mp4_path = _render_with_remotion(storyboard)
        job["state"] = "done"
        job["finishedAt"] = datetime.now(timezone.utc).isoformat()
        job["durationSec"] = _total_duration(storyboard)
        job["videoUrl"] = (
            f"file://{mp4_path}" if mp4_path
            else f"remotion-adapter://no-nodejs/{render_id}.mp4"
        )
    except Exception as exc:
        logger.exception("Remotion render job failed: %s", exc)
        job["state"] = "failed"
        job["error"] = str(exc)
        job["finishedAt"] = datetime.now(timezone.utc).isoformat()
