"""HTTP client for the renderer contract (api/renderer.openapi.yaml v1.0.0).

The renderer URL is read from config.settings.renderer_url.  When empty, the
pipeline uses renderer-stub (started in-process for tests, or as a sidecar).
"""

from __future__ import annotations

import time
import logging

import httpx

from ..models import RenderJob, RenderJobState, RenderRequest, Storyboard

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SEC = 2.0
_DEFAULT_TIMEOUT_SEC = 300.0


class RendererClientError(RuntimeError):
    """Raised when the renderer returns an unexpected response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"Renderer error {status_code} [{code}]: {message}")


class RendererClient:
    """Synchronous HTTP client for the renderer contract.

    Usage::

        client = RendererClient(base_url="https://renderer.run.app/v1")
        job = client.submit(storyboard)
        finished = client.wait(job.render_id)
        print(finished.video_url)
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self._client = httpx.Client(base_url=self._base_url, headers=headers, timeout=30.0)
        self._timeout = timeout

    # ── Public API ──────────────────────────────────────────────────────────

    def submit(self, storyboard: Storyboard, callback_url: str | None = None) -> RenderJob:
        """POST /renders — submit a storyboard; returns a job in state=queued."""
        request = RenderRequest(storyboard=storyboard, callbackUrl=callback_url)
        payload = request.model_dump(by_alias=True, exclude_none=True)

        logger.info("Submitting render", extra={"ticker": storyboard.ticker})
        response = self._client.post("/renders", json=payload)

        if response.status_code == 400:
            err = response.json()
            raise RendererClientError(400, err.get("code", "INVALID"), err.get("message", ""))

        response.raise_for_status()
        return RenderJob.model_validate(response.json())

    def get_job(self, render_id: str) -> RenderJob:
        """GET /renders/{renderId} — poll for current job state."""
        response = self._client.get(f"/renders/{render_id}")

        if response.status_code == 404:
            err = response.json()
            raise RendererClientError(404, err.get("code", "NOT_FOUND"), err.get("message", ""))

        response.raise_for_status()
        return RenderJob.model_validate(response.json())

    def wait(
        self,
        render_id: str,
        poll_interval_sec: float = _DEFAULT_POLL_INTERVAL_SEC,
    ) -> RenderJob:
        """Poll until the job reaches state=done or state=failed."""
        deadline = time.monotonic() + self._timeout

        while True:
            job = self.get_job(render_id)
            logger.debug("Poll render", extra={"render_id": render_id, "state": job.state})

            if job.state == RenderJobState.DONE:
                return job
            if job.state == RenderJobState.FAILED:
                raise RendererClientError(
                    500, "RENDER_FAILED", job.error or "renderer reported failure"
                )

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Render job {render_id!r} did not complete within {self._timeout}s"
                )

            time.sleep(poll_interval_sec)

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "RendererClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
