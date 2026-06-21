"""YMYL content guards.

Three enforced rules:
1. No stock-recommendation phrasing.
2. Mandatory disclaimer shot/segment on every video.
3. Pre-verified financial figures must not be altered by the pipeline
   (renderer immutability is enforced separately at the contract level).
"""

from .ymyl import (
    DisclaimerMissingError,
    RecommendationDetectedError,
    YMYLGuardResult,
    check_script_ymyl,
    check_storyboard_ymyl,
    enforce_script_ymyl,
    enforce_storyboard_ymyl,
)

__all__ = [
    "DisclaimerMissingError",
    "RecommendationDetectedError",
    "YMYLGuardResult",
    "check_script_ymyl",
    "check_storyboard_ymyl",
    "enforce_script_ymyl",
    "enforce_storyboard_ymyl",
]
