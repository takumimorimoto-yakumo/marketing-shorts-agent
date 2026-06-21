"""Content generation package — script generator interface, example, and HTTP client."""

from .interface import ContentGeneratorInterface, StockInfo
from .example import ExampleContentGenerator
from .client import ContentClientError, ContentServiceClient

__all__ = [
    "ContentGeneratorInterface",
    "StockInfo",
    "ExampleContentGenerator",
    "ContentClientError",
    "ContentServiceClient",
]
