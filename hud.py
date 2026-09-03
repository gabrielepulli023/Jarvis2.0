"""Facade di compatibilità HUD. Le implementazioni vivono in hud_ui."""
from hud_ui import HomeView, LogView, ConsoleView
from hud_ui.main_window import MainWindow

JarvisHUD = MainWindow
ActivitySurface = LogView
CommandCenterSurface = ConsoleView
MinimalHomeSurface = HomeView

class ReferenceDataPanel(HomeView):
    def set_rows(self, rows, footer="", progress=0.0): self.rows, self.footer, self.progress = rows, footer, progress

class SystemReferencePanel(HomeView):
    def __init__(self, parent=None): super().__init__(parent); self.history={"cpu":[]}
    def set_data(self, data): self.history["cpu"].append(float(data.get("cpu",0))); self.history["cpu"]=self.history["cpu"][-28:]

class CommandPalette(HomeView):
    from PySide6.QtCore import Signal
    submit=Signal(str)
    def __init__(self,parent=None): super().__init__(parent); from PySide6.QtWidgets import QLineEdit; from PySide6.QtCore import QTimer; self.input=QLineEdit(self); self.persistent=False; self.auto_hide_timer=QTimer(self)
    def set_persistent(self,value): self.persistent=bool(value); self.show()
    def _send(self): value=self.input.text().strip(); self.input.clear(); value and self.submit.emit(value)
