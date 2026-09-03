from __future__ import annotations
import builtins


class JarvisError(Exception):
    """Base for expected, user-reportable JARVIS failures."""


class ToolError(JarvisError):
    pass


class PermissionError(JarvisError, builtins.PermissionError):
    pass


class VerificationError(JarvisError):
    pass


class RecoveryError(JarvisError):
    pass


class BrokerError(JarvisError):
    pass


class VoiceError(JarvisError):
    pass
