"""Shared agent-resolver for agentops-platform clients.

Provides GET-first idempotent agent ensure logic with stale-cache
recovery: when a version POST returns 404 (agent was evicted from the
in-memory platform after a restart) the cache is cleared, the agent is
re-resolved (GET search → POST create if absent), and the caller is given
one retry opportunity.

Both AgentOpsVersionRegisterClient and AgentOpsAnalyticsClient share this
resolver so that the UUID lookup strategy is defined in exactly one place.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_RUNTIME = "adk-cloud-run"


class AgentResolver:
    """Resolve an agent name to its platform UUID, with in-process caching.

    Strategy (GET-first, stale-cache-resilient):
      1. Return the cached agentId immediately if one is stored.
      2. GET /agents — search for an existing agent with a matching name.
      3. If found, store in cache and return its agentId (no POST issued).
      4. If not found, POST /agents to create the agent, cache and return
         the new agentId.

    Stale-cache recovery (called by clients when a subsequent request
    returns 404):
      Call ``invalidate()`` to clear the cache, then call ``ensure()``
      again to re-resolve.  This handles the case where the platform was
      restarted and its in-memory state was wiped, causing the previously
      cached agentId to no longer exist.
    """

    def __init__(self, http: httpx.Client, agent_name: str) -> None:
        self._http = http
        self._agent_name = agent_name
        self._cached_agent_id: str | None = None

    # ── Public ───────────────────────────────────────────────────────────────

    def ensure(self) -> str:
        """Return the platform agentId for this agent, creating it if necessary."""
        if self._cached_agent_id is not None:
            logger.debug(
                "Reusing cached agentId",
                extra={"agent_name": self._agent_name, "agent_id": self._cached_agent_id},
            )
            return self._cached_agent_id

        existing_id = self._find_id_or_none()
        if existing_id is not None:
            logger.info(
                "Found existing agent on platform — reusing",
                extra={"agent_name": self._agent_name, "agent_id": existing_id},
            )
            self._cached_agent_id = existing_id
            return existing_id

        # Agent does not exist — create it.
        resp = self._http.post(
            "/agents",
            json={"name": self._agent_name, "runtime": _RUNTIME},
        )
        resp.raise_for_status()
        new_id: str = resp.json()["agentId"]
        logger.info(
            "Created new agent on platform",
            extra={"agent_name": self._agent_name, "agent_id": new_id},
        )
        self._cached_agent_id = new_id
        return new_id

    def invalidate(self) -> None:
        """Clear the cached agentId so the next ensure() call re-resolves."""
        logger.warning(
            "Invalidating cached agentId (stale after platform restart)",
            extra={"agent_name": self._agent_name, "stale_id": self._cached_agent_id},
        )
        self._cached_agent_id = None

    # ── Private ──────────────────────────────────────────────────────────────

    def _find_id_or_none(self) -> str | None:
        """GET /agents — return the agentId for this agent name, or None."""
        resp = self._http.get("/agents")
        resp.raise_for_status()
        for agent in resp.json():
            if agent.get("name") == self._agent_name:
                return agent["agentId"]
        return None
