"""Isolated contracts and experiments for the biofield architecture."""

from importlib import import_module


_EXPORT_MODULES = {
    "AllocationDecision": ".allocator",
    "AllocationObservation": ".allocator",
    "AllocationPhase": ".allocator",
    "AssignmentMetrics": ".metrics",
    "DynamicsConfig": ".dynamics",
    "EqualAllocator": ".allocator",
    "EvolutionResult": ".dynamics",
    "FieldAllocator": ".allocator",
    "FieldConfig": ".allocator",
    "ResidualStateMachine": ".residual",
    "ResourceLedger": ".ledger",
    "RunArtifactStore": ".artifacts",
    "TrajectoryMetrics": ".metrics",
    "UCBAllocator": ".allocator",
    "evaluate_assignment": ".metrics",
    "evaluate_trajectory": ".metrics",
    "evolve": ".dynamics",
}

__all__ = [
    "AllocationDecision",
    "AllocationObservation",
    "AllocationPhase",
    "AssignmentMetrics",
    "DynamicsConfig",
    "EqualAllocator",
    "EvolutionResult",
    "FieldAllocator",
    "FieldConfig",
    "ResidualStateMachine",
    "ResourceLedger",
    "RunArtifactStore",
    "TrajectoryMetrics",
    "UCBAllocator",
    "evaluate_assignment",
    "evaluate_trajectory",
    "evolve",
]


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
