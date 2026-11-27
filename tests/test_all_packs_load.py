"""Every pack in the repo must load through the run-time loader (pack CI alone never loaded the industry packs)."""
from pathlib import Path

import pytest
import yaml

from usep.ontology_runtime.loader import load_ontology

ROOT = Path(__file__).resolve().parents[1] / "ontology"
PACKS = sorted((yaml.safe_load(p.read_text())["id"], str(yaml.safe_load(p.read_text())["version"]))
               for p in (ROOT / "packs").glob("*/*/pack.yml"))


VERSION = dict(PACKS)
NEEDS = {"app.retail-app-reference": ["industry.retail-reference"]}     # its systems name scopes that pack defines


@pytest.mark.parametrize("pack_id,version", PACKS)
def test_pack_loads(pack_id, version):
    pins = [f"{p}@{VERSION[p]}" for p in (*NEEDS.get(pack_id, []), pack_id)]
    load_ontology(ROOT, pins, allow_reference_only=True)


def test_retail_vocabulary_resolves():
    b = load_ontology(ROOT, ["industry.retail-reference@0.1.0"], allow_reference_only=True)
    assert "MerchandisingPolicy" in b.concepts
