"""Runtime foundation shared by the JARVIS subsystems.

The runtime is loaded lazily so importing a leaf service does not construct every
hardware-facing subsystem or create circular imports.
"""

__all__ = ["CoreRuntime"]


def __getattr__(name):
    if name == "CoreRuntime":
        from .runtime import CoreRuntime

        return CoreRuntime
    raise AttributeError(name)
