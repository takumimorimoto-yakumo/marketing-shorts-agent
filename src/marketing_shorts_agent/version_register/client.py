"""HTTP client for agentops-platform version registration.

Implements VersionRegisterInterface against the live agentops-platform API:
  POST /agents          — ensure agent exists (idempotent by name)
  POST /agents/{id}/versions — register a new version

When AGENTOPS_DRY_RUN=true (default) or when the base URL is empty, all HTTP
calls are skipped and a deterministic mock version-id is returned.

Stale-cache recovery
--------------------
The agentops-platform stores agents in-memory and loses all state on restart
(Cloud Run min-instances=0).  If ``POST /agents/{id}/versions`` returns 404,
it means the previously cached agentId no longer exists.  In that case this
client:
  1. Invalidates the cache via AgentResolver.
  2. Re-resolves the agent (GET search → POST create if absent).
  3. Retries the version POST exactly once.
  4. If the retry also fails, logs a warning and raises (non-fatal for the
     pipeline — the caller is responsible for deciding whether to continue).
"""

from __future__ import annotations

import hashlib
import logging

import httpx

from ..agentops.agent_resolver import AgentResolver
from .interface import VersionRecord, VersionRegisterInterface

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10.0


class AgentOpsVersionRegisterClient(VersionRegisterInterface):
    """Register agent + version with agentops-platform via HTTP.

    Args:
        base_url: Base URL of agentops-platform, e.g. ``https://agentops.run.app/v1``.
        bearer_token: Optional Google-signed ID token for Cloud Run service auth.
        dry_run: When True, skip HTTP and return a deterministic mock version-id.
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
        # AgentResolver handles in-process caching and stale-cache recovery.
        # agent_name is passed via VersionRecord.agent_id at first register() call;
        # we initialise it lazily via _resolver property.
        self._resolver: AgentResolver | None = None

    # ── Public ──────────────────────────────────────────────────────────────

    def register(self, record: VersionRecord) -> str:
        """Register the agent (if needed) then register this version.

        Returns the platform-assigned version id, or a mock id in dry-run mode.
        """
        if self._dry_run or not self._base_url:
            mock_id = self._mock_version_id(record)
            logger.info(
                "[DRY-RUN] Skipping agentops-platform version registration",
                extra={"agent_id": record.agent_id, "version": record.version, "mock_id": mock_id},
            )
            return mock_id

        resolver = self._get_resolver(record.agent_id)
        agent_id = resolver.ensure()
        version_id = self._create_version_with_retry(resolver, agent_id, record)
        logger.info(
            "Registered version with agentops-platform",
            extra={"agent_id": agent_id, "version_id": version_id, "version": record.version},
        )
        return version_id

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AgentOpsVersionRegisterClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Private ─────────────────────────────────────────────────────────────

    def _get_resolver(self, agent_name: str) -> AgentResolver:
        """Return (and lazily create) the AgentResolver for this client."""
        if self._resolver is None:
            self._resolver = AgentResolver(self._http, agent_name)
        return self._resolver

    def _create_version_with_retry(
        self,
        resolver: AgentResolver,
        agent_id: str,
        record: VersionRecord,
    ) -> str:
        """POST /agents/{agentId}/versions with stale-cache recovery on 404.

        If the first attempt returns 404 (platform was restarted and the agent
        no longer exists), the cache is invalidated, the agent is re-resolved,
        and the POST is retried exactly once.  Any subsequent failure raises.
        """
        try:
            return self._create_version(agent_id, record)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

            logger.warning(
                "version POST returned 404 — stale agentId detected, re-resolving agent",
                extra={"stale_agent_id": agent_id, "agent_name": record.agent_id},
            )
            resolver.invalidate()
            new_agent_id = resolver.ensure()
            try:
                return self._create_version(new_agent_id, record)
            except httpx.HTTPStatusError as retry_exc:
                logger.warning(
                    "version POST retry also failed — giving up (non-fatal)",
                    extra={
                        "agent_id": new_agent_id,
                        "status": retry_exc.response.status_code,
                    },
                )
                raise

    def _create_version(self, agent_id: str, record: VersionRecord) -> str:
        """POST /agents/{agentId}/versions — create version."""
        payload: dict[str, str] = {
            "image": record.metadata.get("image", "gcr.io/unknown/unknown:latest"),
            "model": record.metadata.get("model", "gemini-2.5-flash"),
            "promptDigest": hashlib.sha256(
                record.content_generator_class.encode()
            ).hexdigest()[:16],
        }
        if git_commit := record.metadata.get("git_commit"):
            payload["gitCommit"] = git_commit

        resp = self._http.post(f"/agents/{agent_id}/versions", json=payload)
        resp.raise_for_status()
        return resp.json()["versionId"]

    @staticmethod
    def _mock_version_id(record: VersionRecord) -> str:
        digest = hashlib.sha256(
            f"{record.agent_id}:{record.version}:{record.content_generator_class}".encode()
        ).hexdigest()[:12]
        return f"mock-ver-{digest}"
