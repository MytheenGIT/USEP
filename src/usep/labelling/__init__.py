"""Ontology labelling: classify and enrich source records against the pinned ontology (dry-run safe)."""
from usep.labelling.definitions import LabelDefinition, validate_definition
from usep.labelling.labeller import Labeller
from usep.labelling.model import LabelledRecord
from usep.labelling.resolver import effective_properties
from usep.labelling.resolver_types import PropertyDef

__all__ = ["Labeller", "LabelledRecord", "LabelDefinition", "PropertyDef", "validate_definition", "effective_properties"]
