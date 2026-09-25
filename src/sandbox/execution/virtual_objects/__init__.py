"""Virtual objects: custom queries and stored procedures that behave like tables."""

from sandbox.execution.virtual_objects.errors import VirtualObjectError
from sandbox.execution.virtual_objects.models import (
    KIND_PROCEDURE,
    KIND_QUERY,
    ExpansionPlan,
    MaterializeStep,
    VirtualObject,
)
from sandbox.execution.virtual_objects.registry import VirtualObjectSet, registry

__all__ = [
    "KIND_PROCEDURE",
    "KIND_QUERY",
    "ExpansionPlan",
    "MaterializeStep",
    "VirtualObject",
    "VirtualObjectError",
    "VirtualObjectSet",
    "registry",
]
