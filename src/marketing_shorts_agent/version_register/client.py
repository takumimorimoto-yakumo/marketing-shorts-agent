"""HTTP client for agentops-platform version registration.

Implements VersionRegisterInterface against the live agentops-platform API:
  POST /agents          — ensure agent exists (idempotent by name)
  POST /agents/{id}/versions — register a new version

When AGENTOPS_DRY_RUN=true (default) or when the base URL is empty, all HTTP
calls are skipped and a deterministic mock version-id is returned.
"""

from __future__ import annotations

import hashlib
import logging

import httpx

from .interface import VersionRecord, VersionRegisterInterface

logger = logging.getLogger(__name__)

_RUNTIME = "adk-cloud-run"
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
        # In-process cache: avoid repeated GET /agents calls within the same process lifetime.
        self._cached_agent_id: str | None = None

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

        agent_id = self._ensure_agent(record.agent_id)
        version_id = self._create_version(agent_id, record)
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

    def _ensure_agent(self, agent_name: str) -> str:
        """Return the platform agentId for *agent_name*, creating it if necessary.

        Strategy (GET-first):
          1. Return cached agentId immediately if available (in-process cache).
          2. GET /agents — search for an existing agent with a matching name.
          3. If found, store in cache and return its agentId (no POST issued).
          4. If not found, POST /agents to create the agent, cache and return the new agentId.

        This avoids duplicate agent creation when the platform does not return 409
        for duplicate names (i.e. always creates a new agent on POST).
        """
        if self._cached_agent_id is not None:
            logger.debug(
                "Reusing cached agentId",
                extra={"agent_name": agent_name, "agent_id": self._cached_agent_id},
            )
            return self._cached_agent_id

        # Search for existing agent before attempting creation.
        existing_id = self._find_agent_id_or_none(agent_name)
        if existing_id is not None:
            logger.info(
                "Found existing agent on platform — reusing",
                extra={"agent_name": agent_name, "agent_id": existing_id},
            )
            self._cached_agent_id = existing_id
            return existing_id

        # Agent does not exist yet — create it.
        resp = self._http.post(
            "/agents",
            json={"name": agent_name, "runtime": _RUNTIME},
        )
        resp.raise_for_status()
        new_id: str = resp.json()["agentId"]
        logger.info(
            "Created new agent on platform",
            extra={"agent_name": agent_name, "agent_id": new_id},
        )
        self._cached_agent_id = new_id
        return new_id

    def _find_agent_id_or_none(self, agent_name: str) -> str | None:
        """GET /agents — return the agentId for *agent_name*, or None if not found."""
        resp = self._http.get("/agents")
        resp.raise_for_status()
        for agent in resp.json():
            if agent.get("name") == agent_name:
                return agent["agentId"]
        return None

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
