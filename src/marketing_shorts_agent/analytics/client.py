"""HTTP client for agentops-platform metrics ingestion.

Implements AnalyticsInterface.push() against the live agentops-platform API:
  POST /agents/{agentId}/metrics — ingest external outcome metrics

The pull() method is intentionally left as a stub (YouTube Analytics API
integration is out of scope for the bundled public surface).

When AGENTOPS_DRY_RUN=true (default) or when the base URL is empty, the push
call is skipped and only logged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from .interface import AnalyticsInterface, VideoMetrics

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10.0
_METRICS_SOURCE = "youtube-analytics"


class AgentOpsAnalyticsClient(AnalyticsInterface):
    """Push YouTube Analytics metrics to agentops-platform.

    Args:
        base_url: Base URL of agentops-platform, e.g. ``https://agentops.run.app/v1``.
        bearer_token: Optional Google-signed ID token for Cloud Run service auth.
        dry_run: When True, skip HTTP and log instead.
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str | None = None,
        dry_run: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dry_run = dry_run
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self._http = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=_REQUEST_TIMEOUT,
        )

    # ── Public ──────────────────────────────────────────────────────────────

    def pull(self, video_id: str) -> VideoMetrics:
        """Stub: YouTube Analytics pull is a no-op in the public surface.

        A production implementation would call the YouTube Analytics Data API v2
        and return real retention / view counts.  This stub returns zero metrics,
        which is correct behavior when no YouTube credentials are configured.
        """
        logger.info(
            "YouTube Analytics pull is stubbed (no API credentials configured)",
            extra={"video_id": video_id},
        )
        return VideoMetrics(
            video_id=video_id,
            views=0,
            average_view_duration_sec=0.0,
            retention_rate=0.0,
            likes=0,
        )

    def push(self, metrics: VideoMetrics, agent_id: str) -> None:
        """POST /agents/{agentId}/metrics with retention and view metrics.

        In dry-run mode this is a no-op (only logged).
        """
        payload = self._build_payload(metrics, agent_id)

        if self._dry_run or not self._base_url:
            logger.info(
                "[DRY-RUN] Skipping agentops-platform metrics push",
                extra={
                    "agent_id": agent_id,
                    "video_id": metrics.video_id,
                    "samples": len(payload["samples"]),
                },
            )
            return

        resp = self._http.post(f"/agents/{agent_id}/metrics", json=payload)
        resp.raise_for_status()
        logger.info(
            "Pushed metrics to agentops-platform",
            extra={"agent_id": agent_id, "video_id": metrics.video_id, "status": resp.status_code},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AgentOpsAnalyticsClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Private ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_payload(metrics: VideoMetrics, agent_id: str) -> dict:
        """Build MetricIngest payload conforming to agentops-platform OpenAPI schema."""
        observed_at = datetime.now(timezone.utc).isoformat()
        dimensions = {"video_id": metrics.video_id, "agent_id": agent_id}

        samples = [
            {
                "name": "retention_rate",
                "value": metrics.retention_rate,
                "observedAt": observed_at,
                "dimensions": dimensions,
            },
            {
                "name": "views",
                "value": float(metrics.views),
                "observedAt": observed_at,
                "dimensions": dimensions,
            },
            {
                "name": "average_view_duration_sec",
                "value": metrics.average_view_duration_sec,
                "observedAt": observed_at,
                "dimensions": dimensions,
            },
            {
                "name": "likes",
                "value": float(metrics.likes),
                "observedAt": observed_at,
                "dimensions": dimensions,
            },
        ]

        # Include any extra metrics from the VideoMetrics.extra dict
        for name, value in metrics.extra.items():
            if isinstance(value, (int, float)):
                samples.append(
                    {
                        "name": name,
                        "value": float(value),
                        "observedAt": observed_at,
                        "dimensions": dimensions,
                    }
                )

        # versionId is required by the schema.  The pipeline registers a version
        # before calling push(), so metrics.extra["version_id"] should always be
        # present.  An empty string is used as a sentinel for dry-run / test
        # scenarios where no registration has occurred.
        return {
            "versionId": metrics.extra.get("version_id", ""),
            "source": _METRICS_SOURCE,
            "samples": samples,
        }
