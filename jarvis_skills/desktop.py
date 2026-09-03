from __future__ import annotations
import importlib
import threading
import time
from .registry import Capability, SkillManifest, SkillRegistry


def register_desktop_skills(registry: SkillRegistry) -> None:
    from jarvis_windows import InputController

    desktop_input = InputController()

    def call(module, name, *args):
        return getattr(importlib.import_module(module), name)(*args)

    registry.register(
        SkillManifest(
            "windows.list",
            "1.0.0",
            "List visible Windows windows",
            ("list windows", "elenca finestre"),
            frozenset({Capability.READ_SCREEN}),
            "desktop:windows_list",
        ),
        lambda: call("computer", "elenco_finestre"),
    )
    registry.register(
        SkillManifest(
            "windows.focus",
            "1.0.0",
            "Focus a window by title",
            ("focus window", "porta finestra davanti"),
            frozenset({Capability.SYSTEM_SETTINGS}),
            "desktop:focus",
        ),
        lambda title: call("computer", "porta_finestra_davanti", title),
    )
    registry.register(
        SkillManifest(
            "windows.maximize",
            "1.0.0",
            "Maximize a window",
            ("maximize window", "massimizza finestra"),
            frozenset({Capability.SYSTEM_SETTINGS}),
            "desktop:maximize",
        ),
        lambda title: call("computer", "massimizza_finestra", title),
    )
    registry.register(
        SkillManifest(
            "windows.minimize",
            "1.0.0",
            "Minimize a window",
            ("minimize window", "minimizza finestra"),
            frozenset({Capability.SYSTEM_SETTINGS}),
            "desktop:minimize",
        ),
        lambda title: call("computer", "minimizza_finestra", title),
    )
    registry.register(
        SkillManifest(
            "windows.move",
            "1.0.0",
            "Move a window",
            ("move window", "sposta finestra"),
            frozenset({Capability.SYSTEM_SETTINGS}),
            "desktop:move",
        ),
        lambda title, x, y: call("computer", "sposta_finestra", title, int(x), int(y)),
    )
    registry.register(
        SkillManifest(
            "windows.resize",
            "1.0.0",
            "Resize a window",
            ("resize window", "ridimensiona finestra"),
            frozenset({Capability.SYSTEM_SETTINGS}),
            "desktop:resize",
        ),
        lambda title, width, height: call("computer", "ridimensiona_finestra", title, int(width), int(height)),
    )
    registry.register(
        SkillManifest(
            "windows.active",
            "1.0.0",
            "Inspect active window",
            ("active window", "finestra attiva"),
            frozenset({Capability.READ_SCREEN}),
            "desktop:active",
        ),
        lambda: call("computer", "finestra_attiva"),
    )
    registry.register(
        SkillManifest(
            "ui.inspect",
            "1.0.0",
            "Inspect structured UI Automation tree",
            ("inspect ui", "controlli finestra"),
            frozenset({Capability.READ_SCREEN}),
            "desktop:inspect_ui",
        ),
        lambda window_handle=None: call("desktop_intelligence", "inspect_ui", window_handle),
    )
    registry.register(
        SkillManifest(
            "ui.invoke",
            "1.0.0",
            "Invoke a UI Automation control",
            ("invoke control", "premi controllo"),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:ui_invoke",
        ),
        lambda target, window_handle=None: call("desktop_intelligence", "ui_invoke", target, window_handle),
    )
    registry.register(
        SkillManifest(
            "ui.focus",
            "1.0.0",
            "Focus a UI Automation control",
            ("focus control",),
            frozenset({Capability.CONTROL_KEYBOARD}),
            "desktop:ui_focus",
        ),
        lambda target, window_handle=None: call("desktop_intelligence", "ui_focus", target, window_handle),
    )
    registry.register(
        SkillManifest(
            "ui.set_value",
            "1.0.0",
            "Set a UI Automation ValuePattern",
            ("set control value",),
            frozenset({Capability.CONTROL_KEYBOARD}),
            "desktop:ui_set_value",
        ),
        lambda target, value, window_handle=None: call(
            "desktop_intelligence", "ui_set_value", target, value, window_handle
        ),
    )
    registry.register(
        SkillManifest(
            "mouse.move",
            "1.0.0",
            "Move pointer to validated virtual-screen coordinates",
            ("move mouse",),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:mouse_move",
        ),
        desktop_input.move_absolute,
    )
    registry.register(
        SkillManifest(
            "mouse.move_relative",
            "1.0.0",
            "Move pointer relative to its current position",
            ("move mouse relative",),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:mouse_move_relative",
        ),
        desktop_input.move_relative,
    )
    registry.register(
        SkillManifest(
            "mouse.click",
            "1.0.0",
            "Click with a validated button and optional position",
            ("click",),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:mouse_click",
        ),
        desktop_input.click,
    )
    registry.register(
        SkillManifest(
            "mouse.double_click",
            "1.0.0",
            "Double-click at an optional validated position",
            ("double click",),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:mouse_double_click",
        ),
        lambda x=None, y=None, button="left": desktop_input.click(x, y, button, 2),
    )
    registry.register(
        SkillManifest(
            "mouse.right_click",
            "1.0.0",
            "Right-click at an optional validated position",
            ("right click",),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:mouse_right_click",
        ),
        lambda x=None, y=None: desktop_input.click(x, y, "right", 1),
    )
    registry.register(
        SkillManifest(
            "mouse.drag",
            "1.0.0",
            "Drag to validated virtual-screen coordinates",
            ("drag mouse",),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:mouse_drag",
            risk="sensitive",
        ),
        desktop_input.drag,
    )
    registry.register(
        SkillManifest(
            "mouse.scroll",
            "1.0.0",
            "Perform bounded mouse-wheel scrolling",
            ("scroll",),
            frozenset({Capability.CONTROL_MOUSE}),
            "desktop:mouse_scroll",
        ),
        desktop_input.scroll,
    )
    registry.register(
        SkillManifest(
            "keyboard.press",
            "1.0.0",
            "Press a validated key a bounded number of times",
            ("press key",),
            frozenset({Capability.CONTROL_KEYBOARD}),
            "desktop:key_press",
        ),
        desktop_input.press,
    )
    registry.register(
        SkillManifest(
            "keyboard.write",
            "1.0.0",
            "Insert bounded text into the focused control",
            ("write text", "scrivi testo"),
            frozenset({Capability.CONTROL_KEYBOARD}),
            "desktop:key_write",
        ),
        desktop_input.write,
    )
    registry.register(
        SkillManifest(
            "keyboard.hotkey",
            "1.0.0",
            "Send a validated keyboard shortcut",
            ("keyboard shortcut",),
            frozenset({Capability.CONTROL_KEYBOARD}),
            "desktop:hotkey",
        ),
        desktop_input.hotkey,
    )
    registry.register(
        SkillManifest(
            "keyboard.key_down",
            "1.0.0",
            "Hold a validated key until explicitly released",
            ("key down",),
            frozenset({Capability.CONTROL_KEYBOARD}),
            "desktop:key_down",
            risk="sensitive",
        ),
        desktop_input.key_down,
    )
    registry.register(
        SkillManifest(
            "keyboard.key_up",
            "1.0.0",
            "Release a validated key",
            ("key up",),
            frozenset({Capability.CONTROL_KEYBOARD}),
            "desktop:key_up",
        ),
        desktop_input.key_up,
    )


def register_browser_skills(registry: SkillRegistry) -> None:
    from jarvis_browser import ChromeDevToolsClient

    cdp = ChromeDevToolsClient()

    def dom_action(action: str, target: str = "", value: str = "", expected: dict | None = None, timeout: float = 5):
        from chrome_bridge import chrome_action, chrome_snapshot

        before = chrome_snapshot()
        result = chrome_action(action, target, value)
        if not result.get("successo"):
            return result
        baseline = (before.get("dati") or {}).get("received_at", 0)
        deadline = time.monotonic() + max(0.2, min(float(timeout), 15))
        latest: dict = {}
        while time.monotonic() < deadline:
            snapshot = chrome_snapshot()
            if snapshot.get("successo"):
                latest = snapshot.get("dati") or {}
                changed = float(latest.get("received_at", 0)) > float(baseline)
                matches = all(latest.get(k) == v for k, v in (expected or {}).items())
                if changed and matches:
                    return {
                        "successo": True,
                        "messaggio": "Azione DOM verificata.",
                        "dati": {"snapshot": latest, "verified": True},
                    }
            threading.Event().wait(0.1)
        return {
            "successo": False,
            "messaggio": "Azione DOM inviata ma risultato non verificato.",
            "dati": {"snapshot": latest, "verified": False},
        }

    def visual_fallback(
        action: str, target: str = "", value: str = "", expected: dict | None = None, timeout: float = 5
    ):
        from visual_agent import visual_task

        task = (
            f"Nel browser esegui {action} su {target} con valore {value}. Verifica risultato atteso: {expected or {}}"
        )
        return visual_task(task, max_steps=max(2, min(12, int(timeout))))

    registry.register(
        SkillManifest(
            "browser.visual",
            "1.0.0",
            "Vision fallback for browser interaction",
            ("browser visual",),
            frozenset({Capability.READ_SCREEN, Capability.CONTROL_MOUSE, Capability.CONTROL_KEYBOARD}),
            "desktop:visual_browser",
            risk="sensitive",
            timeout=60,
            retries=0,
            verification_strategy="visual_diff",
        ),
        visual_fallback,
    )
    registry.register(
        SkillManifest(
            "browser.cdp",
            "1.0.0",
            "Loopback Chrome DevTools fallback for tab operations",
            ("browser cdp",),
            frozenset({Capability.BROWSER_CONTROL}),
            "desktop:cdp",
            fallbacks=("browser.visual",),
            risk="safe",
            timeout=5,
            retries=0,
            verification_strategy="cdp_response",
        ),
        cdp.action,
    )
    registry.register(
        SkillManifest(
            "browser.dom",
            "1.0.0",
            "Verified Chrome DOM action",
            ("browser click", "browser input", "navigate"),
            frozenset({Capability.BROWSER_CONTROL}),
            "desktop:dom_action",
            fallbacks=("browser.cdp", "browser.visual"),
            risk="safe",
            timeout=15,
            retries=1,
            verification_strategy="fresh_dom_snapshot",
        ),
        dom_action,
    )
    registry.register(
        SkillManifest(
            "browser.snapshot",
            "1.0.0",
            "Read current Chrome DOM snapshot",
            ("browser snapshot", "pagina corrente"),
            frozenset({Capability.BROWSER_CONTROL}),
            "desktop:chrome_snapshot",
        ),
        lambda: importlib.import_module("chrome_bridge").chrome_snapshot(),
    )
