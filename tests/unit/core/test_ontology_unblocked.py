"""The concrete, checkable proof that PR 1 resolves the pre-existing blocker:
`usep.ontology.bundle` and `usep.ontology.gate` import `usep.core.config.Config`,
`usep.core.errors.ConfigError` and `usep.core.models.SourceRecord`, none of which
existed before this PR. This test only asserts the import succeeds and the
expected names resolve — it does not exercise ontology loading itself, which is
out of scope for this phase and already covered by `ontology/tests/test_ontology.py`.
"""

from __future__ import annotations


def test_bundle_and_gate_import_cleanly() -> None:
    from usep.ontology import bundle, gate

    assert bundle.OntologyBundle is not None
    assert bundle.OntologyPins is not None
    assert gate.OntologyGate is not None
    assert gate.GateOutcome is not None


def test_bundle_and_gate_use_the_real_usep_core_names() -> None:
    import usep.core.config
    import usep.core.errors
    import usep.core.models
    from usep.ontology import bundle, gate

    assert bundle.Config is usep.core.config.Config
    assert bundle.ConfigError is usep.core.errors.ConfigError
    assert gate.SourceRecord is usep.core.models.SourceRecord
