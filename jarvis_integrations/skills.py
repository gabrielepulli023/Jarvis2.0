from __future__ import annotations

from jarvis_skills import Capability, SkillManifest, SkillRegistry

from .service import IntegrationService


def register_integration_skills(registry: SkillRegistry, service: IntegrationService) -> None:
    registry.register(
        SkillManifest(
            "external.agent.delegate", "1.0.0", "Delegate a long-horizon GUI/browser task to an external agent",
            ("delegate agent", "agente esterno"),
            frozenset({Capability.CONTROL_MOUSE, Capability.CONTROL_KEYBOARD}),
            "jarvis_integrations:delegate", risk="sensitive", timeout=900.0,
        ),
        lambda task, preferred_backend="auto", max_steps=25: service.delegate(
            task, preferred=preferred_backend, max_steps=int(max_steps)
        ).as_dict(),
    )
    registry.register(
        SkillManifest(
            "external.browser_use.run", "1.0.0", "Run a browser workflow with Browser Use",
            ("browser agent", "browser use"), frozenset({Capability.BROWSER_CONTROL}),
            "jarvis_integrations:browser_use", risk="sensitive", timeout=900.0,
        ),
        lambda task, max_steps=25: service.run_browser(task, max_steps=int(max_steps)).as_dict(),
    )
    registry.register(
        SkillManifest(
            "external.ufo.run", "1.0.0", "Run a Windows desktop workflow through Microsoft UFO",
            ("ufo agent", "desktop agent"), frozenset({Capability.CONTROL_MOUSE, Capability.CONTROL_KEYBOARD}),
            "jarvis_integrations:ufo", risk="sensitive", timeout=900.0,
        ),
        lambda task: service.run_ufo(task).as_dict(),
    )
    registry.register(
        SkillManifest(
            "external.ui_tars.run", "1.0.0", "Run a visual GUI workflow through UI-TARS",
            ("ui tars", "visual gui agent"), frozenset({Capability.READ_SCREEN, Capability.CONTROL_MOUSE, Capability.CONTROL_KEYBOARD}),
            "jarvis_integrations:ui_tars", risk="sensitive", timeout=900.0,
        ),
        lambda task: service.run_ui_tars(task).as_dict(),
    )
    registry.register(
        SkillManifest(
            "external.integrations.status", "1.0.0", "Report external integration availability",
            ("integration status", "stato integrazioni"), frozenset(),
            "jarvis_integrations:status", risk="safe", timeout=15.0,
        ),
        lambda deep=False: {"success": True, "message": "Stato integrazioni caricato.", "data": service.status(deep=bool(deep))},
    )
