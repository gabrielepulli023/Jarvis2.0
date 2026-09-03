from __future__ import annotations

from typing import Any

from .models import IntegrationResult


class PipecatBackend:
    """Adapter per migrare gradualmente la voice pipeline senza sostituire quella stabile."""

    name = "pipecat"

    @staticmethod
    def available() -> bool:
        try:
            import pipecat  # noqa: F401
            return True
        except Exception:
            return False

    def health(self, *, deep: bool = False) -> IntegrationResult:
        if not self.available():
            return IntegrationResult.fail(self.name, "pipecat-ai non installato.")
        try:
            from pipecat.pipeline.pipeline import Pipeline  # noqa: F401
            from pipecat.pipeline.worker import PipelineParams, PipelineWorker  # noqa: F401
            from pipecat.workers.runner import WorkerRunner  # noqa: F401
            return IntegrationResult.ok(self.name, "Pipecat PipelineWorker disponibile")
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"API Pipecat non compatibile: {exc}")

    def build_worker(self, processors: list[Any], **pipeline_params: Any):
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.worker import PipelineParams, PipelineWorker

        pipeline = Pipeline(processors)
        params = PipelineParams(**pipeline_params)
        return PipelineWorker(pipeline, params=params)

    @staticmethod
    def create_runner(**kwargs: Any):
        from pipecat.workers.runner import WorkerRunner
        return WorkerRunner(**kwargs)
