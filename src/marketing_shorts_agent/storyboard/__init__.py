"""Storyboard generation package — converts a Script into a Storyboard."""

from .interface import StoryboardGeneratorInterface
from .example import ExampleStoryboardGenerator

__all__ = ["StoryboardGeneratorInterface", "ExampleStoryboardGenerator"]
