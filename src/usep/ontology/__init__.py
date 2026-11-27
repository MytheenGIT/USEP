"""A read-only view of the ontology for labelling and the graph (HLD 6, 6.1).

The definitions stay in Git as plain files and are read by one loader, `usep.ontology_runtime.load_ontology`, which also
runs gate G1 for the pipeline. This package only reshapes that loader's result. Nothing here writes a definition,
signs a pack or talks to the registry (C-06, C-07 are not built).
"""
from usep.ontology.bundle import OntologyBundle, OntologyPins, PackPin, build_ontology

__all__ = ["OntologyBundle", "OntologyPins", "PackPin", "build_ontology"]
