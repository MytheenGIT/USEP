"""Write the ontology JSON the console expects, for the UI mock and for contract tests.

  python scripts/export_ontology_json.py ui/src/api/fixtures/ontology.json
Uses the reference packs, so the output is placeholder content (reference_only is true on every pack).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from usep.ontology.export import to_dto  # noqa: E402
from usep.ontology import load_ontology, resolve_pins  # noqa: E402

PACKS = ["industry.banking-reference", "org.org-reference", "app.app-reference", "project.project-reference"]
out = Path(sys.argv[1])
dto = to_dto(load_ontology(ROOT / "ontology", resolve_pins(ROOT / "ontology", PACKS), allow_reference_only=True))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(dto, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print(f"{len(dto['concepts'])} concepts, {len(dto['relationships'])} relationships, {len(dto['templates'])} templates -> {out}")
