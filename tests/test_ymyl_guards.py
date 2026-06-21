"""Tests for YMYL guards — the real (non-stub) implementation."""

from __future__ import annotations

import pytest

from marketing_shorts_agent.guards import (
    DisclaimerMissingError,
    RecommendationDetectedError,
    YMYLGuardResult,
    check_script_ymyl,
    check_storyboard_ymyl,
    enforce_script_ymyl,
    enforce_storyboard_ymyl,
)
from marketing_shorts_agent.models import (
    FigureItem,
    Overlay,
    OverlayKind,
    Scene,
    Script,
    ScriptSegment,
    ScriptShotType,
    Shot,
    ShotType,
    Storyboard,
)


# ── Script YMYL checks ────────────────────────────────────────────────────────


class TestScriptYMYLGuard:
    def _make_script(self, segments: list[ScriptSegment]) -> Script:
        return Script(ticker="0001", title="test", segments=segments)

    def test_valid_script_passes(self):
        """A script with disclaimer and no recommendation phrases passes."""
        script = self._make_script([
            ScriptSegment(type=ScriptShotType.HOOK, text="企業概要をお伝えします"),
            ScriptSegment(type=ScriptShotType.NARRATION, text="最新の業績をご紹介します"),
            ScriptSegment(
                type=ScriptShotType.FIGURES,
                text="主要指標です",
                figures=[FigureItem(label="PER", value="12.3x")],
            ),
            ScriptSegment(
                type=ScriptShotType.DISCLAIMER,
                text="【免責事項】投資推奨ではありません。",
            ),
        ])
        result = check_script_ymyl(script)
        assert result.passed
        assert not result.violations

    def test_missing_disclaimer_fails(self):
        """A script without disclaimer segment fails."""
        script = self._make_script([
            ScriptSegment(type=ScriptShotType.HOOK, text="テスト企業"),
            ScriptSegment(type=ScriptShotType.NARRATION, text="業績です"),
        ])
        result = check_script_ymyl(script)
        assert not result.passed
        assert any("disclaimer" in v for v in result.violations)

    def test_recommendation_phrase_detected(self):
        """A script containing '買い推奨' is rejected."""
        script = self._make_script([
            ScriptSegment(type=ScriptShotType.NARRATION, text="この銘柄は買い推奨です"),
            ScriptSegment(type=ScriptShotType.DISCLAIMER, text="免責事項"),
        ])
        result = check_script_ymyl(script)
        assert not result.passed
        assert any("買い推奨" in v or "買い推奨" in v.lower() for v in result.violations)

    def test_buy_recommendation_various_forms(self):
        """Various buy/sell recommendation forms are detected."""
        rec_phrases = [
            "この株を購入を推奨します",
            "今すぐ買え",
            "必ず上がる銘柄です",
            "確実に儲かる",
            "投資推奨銘柄です",
        ]
        for phrase in rec_phrases:
            script = self._make_script([
                ScriptSegment(type=ScriptShotType.NARRATION, text=phrase),
                ScriptSegment(type=ScriptShotType.DISCLAIMER, text="免責"),
            ])
            result = check_script_ymyl(script)
            assert not result.passed, f"Expected violation for phrase: {phrase!r}"

    def test_enforce_raises_disclaimer_missing(self):
        script = self._make_script([
            ScriptSegment(type=ScriptShotType.NARRATION, text="情報提供のみです"),
        ])
        with pytest.raises(DisclaimerMissingError):
            enforce_script_ymyl(script)

    def test_enforce_raises_recommendation(self):
        script = self._make_script([
            ScriptSegment(type=ScriptShotType.NARRATION, text="投資推奨銘柄です"),
            ScriptSegment(type=ScriptShotType.DISCLAIMER, text="免責"),
        ])
        with pytest.raises(RecommendationDetectedError) as exc_info:
            enforce_script_ymyl(script)
        assert len(exc_info.value.violations) > 0


# ── Storyboard YMYL checks ────────────────────────────────────────────────────


class TestStoryboardYMYLGuard:
    def test_valid_storyboard_passes(self, valid_storyboard):
        result = check_storyboard_ymyl(valid_storyboard)
        assert result.passed

    def test_storyboard_without_disclaimer_fails(self, storyboard_without_disclaimer):
        result = check_storyboard_ymyl(storyboard_without_disclaimer)
        assert not result.passed
        assert any("disclaimer" in v for v in result.violations)

    def test_recommendation_in_overlay_detected(self):
        """Recommendation text in an overlay is detected."""
        sb = Storyboard(
            title="Bad Short",
            ticker="0003",
            scenes=[
                Scene(
                    id="intro",
                    shots=[
                        Shot(
                            id="hook-0",
                            type=ShotType.HOOK,
                            overlays=[
                                Overlay(kind=OverlayKind.TEXT, text="この銘柄は買い推奨！")
                            ],
                        )
                    ],
                ),
                Scene(
                    id="close",
                    shots=[
                        Shot(
                            id="disc-0",
                            type=ShotType.DISCLAIMER,
                            overlays=[Overlay(kind=OverlayKind.TEXT, text="免責事項")],
                        )
                    ],
                ),
            ],
        )
        result = check_storyboard_ymyl(sb)
        assert not result.passed

    def test_enforce_storyboard_raises_disclaimer_missing(self, storyboard_without_disclaimer):
        with pytest.raises(DisclaimerMissingError):
            enforce_storyboard_ymyl(storyboard_without_disclaimer)
