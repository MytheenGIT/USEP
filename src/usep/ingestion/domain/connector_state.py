"""The connector state machine: six states, seven transitions, exactly LLD §4.1
Table 11 (section 5.3). Guards (access route tested, reconciliation diff below
threshold, ...) are the caller's responsibility to check *before* calling
`transition()` — this module only enforces which (state, event) pairs exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from usep.core.errors import InvalidStateTransitionError


class ConnectorState(StrEnum):
    DISCOVERED = "DISCOVERED"
    BACKFILLING = "BACKFILLING"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"


class TransitionEvent(StrEnum):
    SCOPE_APPROVED = "scope_approved"
    BACKFILL_COMPLETE = "backfill_complete"
    DEGRADE = "degrade"  # rate limit or 5xx for more than 5 minutes
    RECOVER = "recover"  # source healthy for 10 minutes
    PAUSE = "pause"  # data owner pauses the scope, or permission revoked
    RESUME = "resume"  # data owner resumes
    SCOPE_REMOVED = "scope_removed"  # any state -> DISABLED


@dataclass(frozen=True, slots=True)
class StateRecord:
    state: ConnectorState
    entered_at: datetime
    reason: str = ""


_TABLE: dict[tuple[ConnectorState, TransitionEvent], ConnectorState] = {
    (ConnectorState.DISCOVERED, TransitionEvent.SCOPE_APPROVED): ConnectorState.BACKFILLING,
    (ConnectorState.BACKFILLING, TransitionEvent.BACKFILL_COMPLETE): ConnectorState.LIVE,
    (ConnectorState.LIVE, TransitionEvent.DEGRADE): ConnectorState.DEGRADED,
    (ConnectorState.DEGRADED, TransitionEvent.RECOVER): ConnectorState.LIVE,
    (ConnectorState.LIVE, TransitionEvent.PAUSE): ConnectorState.PAUSED,
    (ConnectorState.DEGRADED, TransitionEvent.PAUSE): ConnectorState.PAUSED,
    (ConnectorState.PAUSED, TransitionEvent.RESUME): ConnectorState.LIVE,
}
for _state in ConnectorState:
    _TABLE[(_state, TransitionEvent.SCOPE_REMOVED)] = ConnectorState.DISABLED


def transition(current: ConnectorState, event: TransitionEvent) -> ConnectorState:
    """The next state for `event` from `current`. Raises `InvalidStateTransitionError`
    if the state machine (Table 11) has no such transition."""
    key = (current, event)
    if key not in _TABLE:
        raise InvalidStateTransitionError(f"no transition for state={current} event={event}")
    return _TABLE[key]
