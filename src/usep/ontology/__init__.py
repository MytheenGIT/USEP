"""Run-time ontology: one loader, gate G1, release events, and a read-only view for labelling and the graph.

The definitions stay in Git as plain files and are read by one loader, `usep.ontology.load_ontology`, which also runs gate
G1 for the pipeline. `usep.ontology.bundle` and `usep.ontology.view` only reshape that loader's result for labelling and the
graph (HLD 6, 6.1); nothing here writes a definition. See ontology/README.md and the Ontology guide.
"""
from usep.ontology.gate import Candidate, GateResult, Quarantine, map_record, validate
from usep.ontology.loader import PackPin, load_ontology, resolve_pins
from usep.ontology.model import OntologyBundle, OntologyRelease

__all__ = ["Candidate", "GateResult", "OntologyBundle", "OntologyRelease", "PackPin", "Quarantine",
           "load_ontology", "map_record", "resolve_pins", "validate"]
