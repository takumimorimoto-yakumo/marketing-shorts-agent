"""Evaluator stub — passes all scripts (for E2E tests without Gemini)."""

from __future__ import annotations

import logging

from ..models import Script
from .interface import EvalResult, EvaluatorInterface

logger = logging.getLogger(__name__)


class EvaluatorStub(EvaluatorInterface):
    """Stub evaluator — always passes. Real evaluator calls Gemini eval model.

    TODO (wave 2): Implement using config.settings.gemini_eval_model with
    structured output to detect recommendation language + quality scoring.
    """

    def evaluate(self, script: Script) -> EvalResult:
        logger.info("[STUB] Evaluating script for %s (stub always passes)", script.ticker)
        return EvalResult(passed=True, score=1.0, notes="stub evaluator — always passes")
