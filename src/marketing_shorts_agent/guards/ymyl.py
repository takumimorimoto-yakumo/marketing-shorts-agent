"""YMYL (You-Money-Your-Life) content guards.

These guards are **real** (not stubbed).  They are called by the pipeline before
sending a storyboard to the renderer and before publishing.

Rules enforced here:
1. No stock-recommendation phrasing detected in any text field.
2. At least one disclaimer shot/segment present.

Rule 3 (figure immutability) is enforced at the renderer-stub boundary and is
tested in the conformance suite, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Script, ScriptShotType, ShotType, Storyboard


# ── Recommendation phrase patterns ────────────────────────────────────────────
#
# Patterns that constitute an investment recommendation in Japanese financial
# content.  Patterns are matched case-insensitively.  Extend this list when
# new problematic phrases are encountered.
#
_RECOMMENDATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # Direct buy/sell recommendations
        r"買[いえ](?:推奨|です|ましょう|時|どき)",
        r"売[りれ](?:推奨|です|ましょう|時|どき)",
        r"購入を?(?:推奨|お勧め|おすすめ)",
        r"売却を?(?:推奨|お勧め|おすすめ)",
        r"今(?:すぐ|すぐに)?買[え]",
        r"今(?:すぐ|すぐに)?売[れ]",
        # Value judgements that imply recommendation
        r"必ず上がる",
        r"絶対(?:に)?(?:上がる|儲かる|お得)",
        r"確実に(?:上がる|儲かる)",
        r"損はない",
        # Explicit recommendation language
        r"投資推奨",
        r"買い推奨",
        r"売り推奨",
        r"target\s*price",
        r"目標株価",
        # Urgency / FOMO phrasing that implies recommendation
        r"買い時",
        r"売り時",
        r"投資判断",
    ]
]


@dataclass
class YMYLGuardResult:
    """Result of a YMYL guard check."""

    passed: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


class RecommendationDetectedError(ValueError):
    """Raised when recommendation phrasing is detected in content."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(
            f"Stock-recommendation phrasing detected ({len(violations)} violation(s)): "
            + "; ".join(violations[:3])
        )


class DisclaimerMissingError(ValueError):
    """Raised when no disclaimer segment/shot is present."""

    def __init__(self) -> None:
        super().__init__(
            "YMYL guard failed: content must include at least one disclaimer segment/shot."
        )


def _detect_recommendation_in_text(text: str) -> list[str]:
    """Return list of violation descriptions found in *text*."""
    violations: list[str] = []
    for pattern in _RECOMMENDATION_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(f"pattern={pattern.pattern!r} matched {match.group()!r}")
    return violations


def check_script_ymyl(script: Script) -> YMYLGuardResult:
    """Validate a Script against YMYL rules.

    Checks:
    1. No recommendation phrasing in any non-disclaimer segment text.
    2. At least one segment with type=disclaimer.

    Disclaimer segments are exempt from recommendation-phrase detection:
    they are expected to contain words like '推奨' in a negative context
    (e.g. '投資を推奨するものではありません').

    Returns a YMYLGuardResult.  Does NOT raise; callers decide whether to raise.
    """
    violations: list[str] = []
    has_disclaimer = False

    for i, segment in enumerate(script.segments):
        if segment.type == ScriptShotType.DISCLAIMER:
            has_disclaimer = True
            continue  # Skip recommendation check in disclaimer text

        text_violations = _detect_recommendation_in_text(segment.text)
        for v in text_violations:
            violations.append(f"segment[{i}] ({segment.type.value}): {v}")

    if not has_disclaimer:
        violations.append("no disclaimer segment found")

    return YMYLGuardResult(passed=len(violations) == 0, violations=violations)


def check_storyboard_ymyl(storyboard: Storyboard) -> YMYLGuardResult:
    """Validate a Storyboard against YMYL rules.

    Checks:
    1. No recommendation phrasing in any non-disclaimer overlay text.
    2. At least one shot with type=disclaimer.

    Disclaimer shots are exempt from recommendation-phrase detection (same
    logic as check_script_ymyl).

    Returns a YMYLGuardResult.  Does NOT raise; callers decide whether to raise.
    """
    violations: list[str] = []

    if not storyboard.has_disclaimer():
        violations.append("no disclaimer shot found in storyboard")

    for si, scene in enumerate(storyboard.scenes):
        for sh, shot in enumerate(scene.shots):
            if shot.type == ShotType.DISCLAIMER:
                continue  # Skip recommendation check in disclaimer shots
            for oi, overlay in enumerate(shot.overlays):
                text = overlay.text or ""
                text_violations = _detect_recommendation_in_text(text)
                for v in text_violations:
                    violations.append(
                        f"scene[{si}].shot[{sh}].overlay[{oi}]: {v}"
                    )

    return YMYLGuardResult(passed=len(violations) == 0, violations=violations)


def enforce_script_ymyl(script: Script) -> None:
    """Run YMYL guard on a Script; raise on any violation."""
    result = check_script_ymyl(script)
    if not result.passed:
        # Distinguish recommendation violations from missing disclaimer
        rec_violations = [v for v in result.violations if "disclaimer" not in v]
        if rec_violations:
            raise RecommendationDetectedError(rec_violations)
        raise DisclaimerMissingError()


def enforce_storyboard_ymyl(storyboard: Storyboard) -> None:
    """Run YMYL guard on a Storyboard; raise on any violation."""
    result = check_storyboard_ymyl(storyboard)
    if not result.passed:
        rec_violations = [v for v in result.violations if "disclaimer" not in v]
        if rec_violations:
            raise RecommendationDetectedError(rec_violations)
        raise DisclaimerMissingError()
