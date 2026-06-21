"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marketing_shorts_agent.models import (
    ClipIntent,
    ClipKind,
    FigureItem,
    Overlay,
    OverlayKind,
    Scene,
    Shot,
    ShotType,
    Storyboard,
)


# ── Storyboard fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def valid_storyboard() -> Storyboard:
    """Minimal valid storyboard with disclaimer."""
    return Storyboard(
        title="Test Short",
        ticker="0001",
        scenes=[
            Scene(
                id="intro",
                shots=[
                    Shot(
                        id="hook-0",
                        type=ShotType.HOOK,
                        overlays=[Overlay(kind=OverlayKind.TEXT, text="テスト企業の解説です")],
                    )
                ],
            ),
            Scene(
                id="figures",
                shots=[
                    Shot(
                        id="figures-0",
                        type=ShotType.FIGURES,
                        overlays=[
                            Overlay(kind=OverlayKind.FIGURE, label="PER", value="12.3x"),
                            Overlay(kind=OverlayKind.FIGURE, label="PBR", value="1.2x"),
                        ],
                    )
                ],
            ),
            Scene(
                id="close",
                shots=[
                    Shot(
                        id="disclaimer-0",
                        type=ShotType.DISCLAIMER,
                        overlays=[
                            Overlay(
                                kind=OverlayKind.TEXT,
                                text="【免責事項】この動画は情報提供のみを目的としており投資推奨ではありません。",
                            )
                        ],
                    )
                ],
            ),
        ],
    )


@pytest.fixture
def storyboard_without_disclaimer() -> Storyboard:
    """Storyboard missing disclaimer — should be rejected."""
    return Storyboard(
        title="No Disclaimer Short",
        ticker="0002",
        scenes=[
            Scene(
                id="intro",
                shots=[
                    Shot(
                        id="hook-0",
                        type=ShotType.HOOK,
                        overlays=[Overlay(kind=OverlayKind.TEXT, text="これはテストです")],
                    )
                ],
            ),
        ],
    )


# ── Renderer stub client fixture ──────────────────────────────────────────────


@pytest.fixture
def stub_client() -> TestClient:
    """FastAPI test client for renderer-stub."""
    from renderer_stub.app import app

    return TestClient(app, raise_server_exceptions=True)
