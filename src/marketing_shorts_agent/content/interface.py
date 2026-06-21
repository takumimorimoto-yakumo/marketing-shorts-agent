"""Abstract interface for script content generators.

A production generator (private) is swapped in via config by pointing
CONTENT_GENERATOR_CLASS to a fully-qualified class name. This repo bundles
ExampleContentGenerator as the default.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import FigureItem, Script


@dataclass
class StockInfo:
    """Minimal stock data required to generate a script."""

    ticker: str
    company_name: str
    sector: str
    figures: list[FigureItem]
    """Pre-verified financial figures from an official primary data source."""


class ContentGeneratorInterface(ABC):
    """Abstract base class for script generators.

    Subclass this to swap in a production generator without changing the pipeline.
    The pipeline calls ``generate(stock_info)`` and expects a YMYL-compliant Script.
    """

    @abstractmethod
    def generate(self, stock_info: StockInfo) -> Script:
        """Generate a structured script for a given stock.

        The returned Script MUST:
        - contain at least one segment with type=disclaimer
        - contain no stock-recommendation phrasing

        The pipeline enforces these constraints via YMYL guards after this call.
        """
        ...
