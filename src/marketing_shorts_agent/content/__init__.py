"""Content generation package — script generator interface and generic example."""

from .interface import ContentGeneratorInterface, StockInfo
from .example import ExampleContentGenerator

__all__ = ["ContentGeneratorInterface", "StockInfo", "ExampleContentGenerator"]
