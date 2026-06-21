"""Version register — register script/prompt versions with agentops-platform."""

from .interface import VersionRegisterInterface, VersionRecord
from .stub import VersionRegisterStub

__all__ = ["VersionRegisterInterface", "VersionRecord", "VersionRegisterStub"]
