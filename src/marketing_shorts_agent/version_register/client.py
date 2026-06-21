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
        """POST /agents — register agent (idempotent).

        The platform may return 409 if the agent already exists; we handle that
        by re-listing agents and finding the matching name.
        Returns the platform agentId.
        """
        resp = self._http.post(
            "/agents",
            json={"name": agent_name, "runtime": _RUNTIME},
        )
        if resp.status_code == 201:
            return resp.json()["agentId"]
        if resp.status_code in (409, 422):
            # Agent already registered — find its id
            return self._find_agent_id(agent_name)
        resp.raise_for_status()
        return resp.json()["agentId"]  # unreachable, satisfies type checker

    def _find_agent_id(self, agent_name: str) -> str:
        """GET /agents — find agent by name."""
        resp = self._http.get("/agents")
        resp.raise_for_status()
        for agent in resp.json():
            if agent.get("name") == agent_name:
                return agent["agentId"]
        raise RuntimeError(f"Agent '{agent_name}' not found after registration conflict")

    def _create_version(self, agent_id: str, record: VersionRecord) -> str:
        """POST /agents/{agentId}/versions — create version."""
        payload: dict[str, str] = {
            "image": record.metadata.get("image", "gcr.io/unknown/unknown:latest"),
            "model": record.metadata.get("model", "gemini-2.0-flash-001"),
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
