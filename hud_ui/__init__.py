"""UI ufficiale JARVIS: view indipendenti e palette condivisa."""

from .orb_widget import OrbWidget
from .home_view import HomeView
from .log_view import LogView
from .console_view import ConsoleView
from .startup_view import StartupView
from .minimized_orb import MinimizedOrb

__all__ = ["OrbWidget", "HomeView", "LogView", "ConsoleView", "StartupView", "MinimizedOrb"]
