"""Fabric writer (C-04). Decision record: docs/adr/ADR-21-fabric-writer-and-postgres-commit-point.md."""
from usep.fabric.consumer import FabricConsumer
from usep.fabric.outbox import OutboxRelay
from usep.fabric.writer import FabricWriter

__all__ = ["FabricConsumer", "FabricWriter", "OutboxRelay"]
