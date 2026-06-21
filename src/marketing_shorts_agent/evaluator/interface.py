"""Abstract evaluator interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import Script


@dataclass
class EvalResult:
    passed: bool
    score: float
    """0.0 – 1.0"""
    violations: list[str] = field(default_factory=list)
    notes: str = ""


class EvaluatorInterface(ABC):
    """Evaluate script quality and YMYL compliance via Gemini."""

    @abstractmethod
    def evaluate(self, script: Script) -> EvalResult:
        """Run quality + YMYL evaluation on a Script. Return EvalResult."""
        ...
