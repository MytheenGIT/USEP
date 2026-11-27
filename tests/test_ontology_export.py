"""The ontology JSON the console reads (docs/ui-ontology-view-brief.md): shape, no leakage, in step with the loader."""
import json
from pathlib import Path

from usep.ontology.export import to_dto
from usep.ontology_runtime import load_ontology, resolve_pins

ROOT = Path(__file__).resolve().parents[1] / "ontology"
PACKS = ["industry.banking-reference", "org.org-reference", "app.app-reference", "project.project-reference"]
FIXTURE = ROOT.parent / "ui" / "src" / "api" / "fixtures" / "ontology.json"


def dto():
    return to_dto(load_ontology(ROOT, resolve_pins(ROOT, PACKS), allow_reference_only=True))


def test_dto_matches_the_loader_and_is_json():
    d = dto()
    assert json.loads(json.dumps(d)) == d
    assert {c["id"] for c in d["concepts"]} >= {"Service", "Team", "ComplianceControl"}
    assert {t["pack_id"] for t in d["templates"]} == {"core", "app.app-reference"}
    svc = next(c for c in d["concepts"] if c["id"] == "ComplianceControl")
    assert svc["parent"] == "Control" and any(a["defined_in"] == "Control" for a in svc["attributes"])
    assert all(p["reference_only"] for p in d["packs"] if p["id"] != "core")


def test_dto_holds_definitions_only():
    text = json.dumps(dto())
    for word in ("tenant_id\":", "password", "token", "secret"):
        assert word not in text.replace('"role_only"', "")


def test_ui_fixture_is_current():
    """Regenerate with scripts/export_ontology_json.py when the ontology changes."""
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == json.loads(json.dumps(dto()))
