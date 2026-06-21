"""Evaluator hook — Gemini-based content quality evaluation."""

from .interface import EvaluatorInterface, EvalResult
from .stub import EvaluatorStub

__all__ = ["EvaluatorInterface", "EvalResult", "EvaluatorStub"]
