import shutil
from pathlib import Path

import pytest

from usep.ontology.bundle import OntologyBundle
from usep.ontology.view import OntologyView

ROOT = Path(__file__).resolve().parents[2] / "ontology"
PACKS = ["industry.banking-reference", "org.org-reference", "app.app-reference", "project.project-reference"]
T1, T2 = "00000000-0000-7000-8000-000000000001", "00000000-0000-7000-8000-000000000002"

GRC = """source_system: grc
on_unmapped: quarantine
mappings:
  - source_object: control
    entity: ComplianceControl
    fields: {name: title, control_set: framework, source_id: id}
"""


@pytest.fixture(scope="session")
def view(tmp_path_factory) -> OntologyView:
    """The real ontology plus a test-only GRC mapping to a banking subclass and a 'Squad' glossary term."""
    root = tmp_path_factory.mktemp("onto") / "ontology"
    shutil.copytree(ROOT, root)
    (root / "packs/app/app-reference/mappings/grc.yml").write_text(GRC, encoding="utf-8")
    g = root / "packs/org/org-reference/glossary.yml"
    g.write_text(g.read_text(encoding="utf-8").replace("terms:\n", "terms:\n  - {term: Squad, maps_to: Team, status: test}\n", 1), encoding="utf-8")
    bundle = OntologyBundle.load(root, PACKS, allow_reference=True)
    return OntologyView(bundle, root)
