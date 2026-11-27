"""One loader for both run-times (D7). The golden file was taken from the old, separate loader before it was removed:
this test keeps labelling and the graph seeing exactly what they saw then, for four pack stacks."""
import json
from pathlib import Path

import pytest

from tests.ontology_snapshot import COMBOS, snapshot
from usep.ontology.bundle import OntologyBundle
from usep.ontology import load_ontology, resolve_pins

GOLD = json.loads((Path(__file__).parent / "golden" / "ontology_view_snapshot.json").read_text(encoding="utf-8"))
ROOT = Path(__file__).resolve().parents[1] / "ontology"


@pytest.mark.parametrize("name", sorted(COMBOS))
def test_view_matches_the_golden_snapshot(name):
    assert json.loads(json.dumps(snapshot(COMBOS[name]))) == GOLD[name]


@pytest.mark.parametrize("name", sorted(COMBOS))
def test_both_entry_points_share_one_digest_and_one_loader(name):
    ids = COMBOS[name]
    a = OntologyBundle.load(ROOT, ids, allow_reference=True)
    b = load_ontology(ROOT, resolve_pins(ROOT, ids), allow_reference_only=True)
    assert a.pins.digest == b.release.digest
    assert set(a.concepts) == set(b.concepts) and a.relationships == frozenset(b.relationships)


def test_view_rejects_what_the_loader_rejects():
    from usep.core.errors import OntologyLoadError
    with pytest.raises(OntologyLoadError, match="reference-only"):
        OntologyBundle.load(ROOT, ["industry.banking-reference"])
    with pytest.raises(OntologyLoadError, match="not found"):
        OntologyBundle.load(ROOT, ["no.such-pack"], allow_reference=True)
