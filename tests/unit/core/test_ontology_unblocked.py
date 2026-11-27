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
    # The gate is the one run-time gate G1 (usep.ontology.gate): map a source record to a concept, then validate it.
    assert callable(gate.map_record) and callable(gate.validate)
    assert gate.Candidate is not None and gate.Quarantine is not None and gate.GateResult is not None


def test_bundle_and_gate_use_the_real_usep_core_names() -> None:
    import usep.core.config
    import usep.core.errors
    from usep.ontology import bundle, loader

    assert bundle.Config is usep.core.config.Config
    # The loader fails closed with the one OntologyLoadError, which is part of the shared usep error hierarchy.
    assert loader.OntologyLoadError is usep.core.errors.OntologyLoadError
    assert issubclass(usep.core.errors.OntologyLoadError, usep.core.errors.UsepError)
