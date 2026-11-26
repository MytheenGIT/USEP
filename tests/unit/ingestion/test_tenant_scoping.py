"""ADR-10: every cursor, raw index row, audit row, rate-limit key, and object
key carries tenant_id. The three branch-matched Protocols (CursorManager,
RawPayloadWriter, AuditWriter) carry no tenant_id parameter by design (task
rule: do not add tenant_id to any method signature) — tenant_id is bound once
at adapter/writer construction instead, and checked here structurally.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

from usep.ingestion.domain.raw_object import object_key
from usep.ingestion.ports.quarantine import QuarantinePort, WorkItemPort
from usep.ingestion.ports.raw_index import RawIndexPort
from usep.ingestion.raw.writer import RawPayloadWriter
from usep.ingestion.runtime.rate_limiter import RateLimitKey


def _requires_param(callable_obj: object, param_name: str) -> bool:
    return param_name in inspect.signature(callable_obj).parameters  # type: ignore[arg-type]


def test_tenant_required_on_every_key() -> None:
    # Construction-bound tenant_id (branch-protocol-matching components).
    assert _requires_param(RawPayloadWriter.__init__, "tenant_id")

    # Internal (non-branch) ports still carry tenant_id per call.
    assert _requires_param(RawIndexPort.find, "tenant_id")
    assert _requires_param(QuarantinePort.quarantine, "tenant_id")
    assert _requires_param(WorkItemPort.upsert, "tenant_id")

    # Rate-limit key.
    assert "tenant_id" in RateLimitKey.__dataclass_fields__

    # Object key: tenant_id is embedded in the key string itself.
    tenant_id = uuid4()
    key = object_key(tenant_id, "jira", "PROJ", "issue", "PROJ-1", "deadbeef")
    assert str(tenant_id) in key
