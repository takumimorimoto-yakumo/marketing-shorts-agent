"""Storyboard generation package — converts a Script into a Storyboard."""

from .interface import StoryboardGeneratorInterface
from .example import ExampleStoryboardGenerator
from .client import StoryboardClientError, StoryboardServiceClient

__all__ = [
    "StoryboardGeneratorInterface",
    "ExampleStoryboardGenerator",
    "StoryboardClientError",
    "StoryboardServiceClient",
]
