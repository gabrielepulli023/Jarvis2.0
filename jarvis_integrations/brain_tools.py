from __future__ import annotations

from .service import get_integration_service


def integration_status(deep=False):
    data = get_integration_service().status(deep=bool(deep))
    online = sum(1 for row in data.values() if row.get("successo"))
    return {"successo": True, "messaggio": f"Integrazioni controllate: {online}/{len(data)} disponibili o configurate.", "dati": data}


def delegate_agent_task(task, preferred_backend="auto", max_steps=25):
    return get_integration_service().delegate(task, preferred=preferred_backend, max_steps=max_steps).as_dict()


def browser_agent_task(task, max_steps=25):
    return get_integration_service().run_browser(task, max_steps=max_steps).as_dict()


def ufo_agent_task(task):
    return get_integration_service().run_ufo(task).as_dict()


def ui_tars_agent_task(task):
    return get_integration_service().run_ui_tars(task).as_dict()


def mem0_search(query, limit=6):
    service = get_integration_service()
    if not service.config.mem0_enabled:
        return {"successo": False, "messaggio": "Mem0 disabilitato."}
    return service.mem0.search(query, limit=limit).as_dict()


def mem0_remember(text):
    service = get_integration_service()
    if not service.config.mem0_enabled:
        return {"successo": False, "messaggio": "Mem0 disabilitato."}
    return service.mem0.add_fact(text).as_dict()
