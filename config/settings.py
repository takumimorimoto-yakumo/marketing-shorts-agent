"""Central config loaded from environment / .env file.

All hard-coded values are forbidden. This module is the single source of truth
for every configurable value in the pipeline.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pipeline configuration.  All values come from environment variables or
    a ``.env`` file in the project root (never hard-coded in application code).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Renderer ────────────────────────────────────────────────────────────
    renderer_url: str = Field(
        default="",
        description="Base URL of the renderer service. Empty → use bundled stub.",
    )

    # ── Google Cloud ─────────────────────────────────────────────────────────
    google_cloud_project: str = Field(default="", description="GCP project id.")
    google_cloud_region: str = Field(default="us-central1")

    # ── Model IDs ────────────────────────────────────────────────────────────
    gemini_script_model: str = Field(default="gemini-2.0-flash-001")
    gemini_storyboard_model: str = Field(default="gemini-2.0-flash-001")
    gemini_eval_model: str = Field(default="gemini-2.0-flash-001")
    veo_model: str = Field(default="veo-3.0-generate-preview")
    imagen_model: str = Field(default="imagen-3.0-generate-001")
    chirp_voice: str = Field(default="ja-JP-Standard-D")
    lyria_model: str = Field(default="lyria-2")

    # ── YouTube ──────────────────────────────────────────────────────────────
    youtube_client_secrets_file: str = Field(default="")
    youtube_channel_id: str = Field(default="")

    # ── agentops-platform ────────────────────────────────────────────────────
    agentops_base_url: str = Field(default="https://agentops-platform.run.app")
    agentops_agent_id: str = Field(default="marketing-shorts-agent")
    agentops_api_key: str = Field(default="")

    # ── Runtime ──────────────────────────────────────────────────────────────
    dry_run: bool = Field(default=True)
    log_level: str = Field(default="INFO")

    # ── Renderer-stub ────────────────────────────────────────────────────────
    renderer_stub_port: int = Field(default=8080)


# Module-level singleton; import and use ``settings`` everywhere.
settings = Settings()
