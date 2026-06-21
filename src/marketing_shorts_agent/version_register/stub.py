"""Version register stub."""

from __future__ import annotations

import logging
import uuid

from .interface import VersionRecord, VersionRegisterInterface

logger = logging.getLogger(__name__)


class VersionRegisterStub(VersionRegisterInterface):
    """Stub — logs registration, returns a fake version id.

    TODO (wave 2): Implement with httpx POST to agentops-platform /agents/{id}/versions.
    """

    def register(self, record: VersionRecord) -> str:
        version_id = f"stub-ver-{uuid.uuid4().hex[:8]}"
        logger.info(
            "[STUB] Would register version with agentops-platform",
            extra={
                "agent_id": record.agent_id,
                "version": record.version,
                "version_id": version_id,
            },
        )
        return version_id
