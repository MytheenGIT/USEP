from __future__ import annotations

import pytest

from usep.core.errors import InvalidStateTransitionError
from usep.ingestion.domain.connector_state import ConnectorState, TransitionEvent, transition


def test_state_machine_seven_transitions() -> None:
    """LLD §4.1, Table 11: all seven listed transitions (six explicit plus the
    'any state -> DISABLED' scope-removal rule applied to all six states, of which
    we check the ones distinct from the six already covered)."""
    assert transition(ConnectorState.DISCOVERED, TransitionEvent.SCOPE_APPROVED) == ConnectorState.BACKFILLING
    assert transition(ConnectorState.BACKFILLING, TransitionEvent.BACKFILL_COMPLETE) == ConnectorState.LIVE
    assert transition(ConnectorState.LIVE, TransitionEvent.DEGRADE) == ConnectorState.DEGRADED
    assert transition(ConnectorState.DEGRADED, TransitionEvent.RECOVER) == ConnectorState.LIVE
    assert transition(ConnectorState.LIVE, TransitionEvent.PAUSE) == ConnectorState.PAUSED
    assert transition(ConnectorState.PAUSED, TransitionEvent.RESUME) == ConnectorState.LIVE
    assert transition(ConnectorState.DISCOVERED, TransitionEvent.SCOPE_REMOVED) == ConnectorState.DISABLED


@pytest.mark.parametrize("state", list(ConnectorState))
def test_scope_removed_disables_from_any_state(state: ConnectorState) -> None:
    assert transition(state, TransitionEvent.SCOPE_REMOVED) == ConnectorState.DISABLED


def test_degraded_also_pauses() -> None:
    assert transition(ConnectorState.DEGRADED, TransitionEvent.PAUSE) == ConnectorState.PAUSED


def test_invalid_state_transition_rejected_and_audited() -> None:
    """The 'audited' half of this requirement is the caller's job (it wraps this
    call and writes an audit_event on the raised exception, PR 5's orchestration);
    this test covers the raising half."""
    with pytest.raises(InvalidStateTransitionError):
        transition(ConnectorState.DISABLED, TransitionEvent.RESUME)
    with pytest.raises(InvalidStateTransitionError):
        transition(ConnectorState.DISCOVERED, TransitionEvent.BACKFILL_COMPLETE)
    with pytest.raises(InvalidStateTransitionError):
        transition(ConnectorState.PAUSED, TransitionEvent.DEGRADE)
