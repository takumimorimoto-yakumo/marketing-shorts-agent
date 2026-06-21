"""HTTP client for the content service contract (api/content.openapi.yaml v1.0.0).

The content service URL is read from config via CONTENT_URL.  When empty,
the pipeline uses content-stub (started in-process or as a sidecar).
"""

from __future__ import annotations

import logging

import httpx

from ..models import FigureItem, Script, ScriptSegment, ScriptShotType
from .interface import ContentGeneratorInterface, StockInfo

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 60.0


class ContentClientError(RuntimeError):
    """Raised when the content service returns an unexpected response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"Content service error {status_code} [{code}]: {message}")


class ContentServiceClient(ContentGeneratorInterface):
    """HTTP client for the content service contract.

    Implements ContentGeneratorInterface so it can be used as a drop-in
    replacement for in-process generators in PipelineOrchestrator.

    Usage::

        client = ContentServiceClient(base_url="https://content.run.app/v1")
        script = client.generate(stock_info)
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
        self._client = httpx.Client(base_url=self._base_url, headers=headers, timeout=timeout)

    # ── ContentGeneratorInterface ────────────────────────────────────────────

    def generate(self, stock_info: StockInfo) -> Script:
        """POST /scripts — generate a script for the given stock.

        Raises ContentClientError on 4xx/5xx.
        """
        payload = {
            "ticker": stock_info.ticker,
            "company_name": stock_info.company_name,
            "sector": stock_info.sector,
            "figures": [
                {"label": f.label, "value": f.value} for f in stock_info.figures
            ],
        }

        logger.info("Requesting script from content service", extra={"ticker": stock_info.ticker})
        response = self._client.post("/scripts", json=payload)

        if response.status_code == 400:
            err = response.json()
            detail = err.get("detail", err)
            if isinstance(detail, dict):
                raise ContentClientError(
                    400,
                    detail.get("code", "INVALID"),
                    detail.get("message", ""),
                )
            raise ContentClientError(400, "INVALID", str(detail))

        response.raise_for_status()
        return _wire_to_script(response.json())

    # ── Resource management ─────────────────────────────────────────────────

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "ContentServiceClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── Wire-format deserialisation ───────────────────────────────────────────────


def _wire_to_script(data: dict) -> Script:
    """Deserialise the content service wire format into a Script domain model."""
    segments: list[ScriptSegment] = []
    for seg in data.get("segments", []):
        figures = [
            FigureItem(label=f["label"], value=f["value"])
            for f in seg.get("figures", [])
        ]
        segments.append(
            ScriptSegment(
                type=ScriptShotType(seg["type"]),
                text=seg["text"],
                figures=figures,
                duration_sec=seg.get("duration_sec"),
            )
        )
    return Script(
        ticker=data["ticker"],
        title=data["title"],
        segments=segments,
    )
