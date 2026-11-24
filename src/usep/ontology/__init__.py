"""The ontology at run time: load the core and the pinned packs from usep/ontology/ (HLD 6, 6.1),
pin their versions, and check records against them (gate G1).

The definitions stay in Git as plain files. This package only reads them. Nothing here writes a
definition, signs a pack or talks to the registry (C-06, C-07 are not built).
"""
from usep.ontology.bundle import OntologyBundle, OntologyPins, PackPin, build_ontology
from usep.ontology.gate import GateOutcome, OntologyGate

__all__ = ["OntologyBundle", "OntologyPins", "PackPin", "OntologyGate", "GateOutcome", "build_ontology"]
