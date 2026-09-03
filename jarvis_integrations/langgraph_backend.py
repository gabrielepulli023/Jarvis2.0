from __future__ import annotations

from typing import Callable, TypedDict

from .models import IntegrationResult


class AgentState(TypedDict, total=False):
    task: str
    candidates: list[str]
    index: int
    backend: str
    result: IntegrationResult


class LangGraphBackend:
    name = "langgraph"

    @staticmethod
    def available() -> bool:
        try:
            import langgraph  # noqa: F401
            return True
        except Exception:
            return False

    def health(self, *, deep: bool = False) -> IntegrationResult:
        return (
            IntegrationResult.ok(self.name, "LangGraph disponibile")
            if self.available()
            else IntegrationResult.fail(self.name, "langgraph non installato.")
        )

    def run(
        self,
        task: str,
        candidates: list[str],
        execute: Callable[[str, str], IntegrationResult],
    ) -> IntegrationResult:
        if not candidates:
            return IntegrationResult.fail(self.name, "Nessun backend candidato.")
        if not self.available():
            # Deterministic fallback keeps JARVIS operational before optional deps are installed.
            last = None
            for backend in candidates:
                last = execute(backend, task)
                if last.success:
                    return last
            return last or IntegrationResult.fail(self.name, "Nessun backend ha completato il task.")

        from langgraph.graph import END, START, StateGraph

        def plan(state: AgentState):
            idx = int(state.get("index", 0))
            return {"backend": state["candidates"][idx]}

        def execute_node(state: AgentState):
            return {"result": execute(state["backend"], state["task"])}

        def decide_next(state: AgentState):
            result = state["result"]
            idx = int(state.get("index", 0))
            if result.success or idx + 1 >= len(state["candidates"]):
                return "end"
            return "retry"

        def advance(state: AgentState):
            return {"index": int(state.get("index", 0)) + 1}

        graph = StateGraph(AgentState)
        graph.add_node("plan", plan)
        graph.add_node("execute", execute_node)
        graph.add_node("advance", advance)
        graph.add_edge(START, "plan")
        graph.add_edge("plan", "execute")
        graph.add_conditional_edges("execute", decide_next, {"end": END, "retry": "advance"})
        graph.add_edge("advance", "plan")
        compiled = graph.compile()
        state = compiled.invoke({"task": str(task), "candidates": list(candidates), "index": 0})
        return state.get("result") or IntegrationResult.fail(self.name, "Workflow LangGraph senza risultato.")
