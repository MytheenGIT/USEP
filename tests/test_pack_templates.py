"""Pack-level query templates (D2): the loader reads them, and pack CI holds them to the core's rules."""
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from usep.core.errors import OntologyLoadError
from usep.ontology_runtime import load_ontology

ROOT = Path(__file__).resolve().parents[1] / "ontology"
sys.path.insert(0, str(ROOT / "tools"))
import check_ontology as co  # noqa: E402

PINS = ["app.app-reference@0.1.0"]


@pytest.fixture()
def onto(tmp_path):
    dst = tmp_path / "ontology"
    shutil.copytree(ROOT, dst)
    return dst


def app_pack(root):
    return root / "packs/app/app-reference"


def ci_errors(root):
    old, co.ROOT = co.ROOT, root
    try:
        rep = co.Report()
        co.check_pack_templates(rep, co.check_core(co.Report()))
        return rep.errors
    finally:
        co.ROOT = old


def edit_template(root, name, fn):
    p = app_pack(root) / "templates" / f"{name}.yml"
    t = yaml.safe_load(p.read_text(encoding="utf-8"))
    fn(t)
    p.write_text(yaml.safe_dump(t, sort_keys=False), encoding="utf-8")


def test_loader_reads_pack_templates_and_core_ones_are_unchanged():
    b = load_ontology(ROOT, PINS, allow_reference_only=True)
    assert {"app_references_of", "app_documents_of"} <= set(b.templates)
    assert b.templates["app_references_of"].pack_id == "app.app-reference"
    assert b.templates["owner_of"].pack_id == ""
    assert "app_references_of" not in load_ontology(ROOT, [], allow_reference_only=True).templates   # only pinned packs


def test_pinned_pack_templates_change_the_digest():
    assert load_ontology(ROOT, PINS, allow_reference_only=True).release.digest != \
        load_ontology(ROOT, [], allow_reference_only=True).release.digest


def test_real_packs_pass_pack_ci():
    assert ci_errors(ROOT) == []


def test_loader_rejects_a_pack_template_without_tenant_filter(onto):
    edit_template(onto, "app_documents_of", lambda t: t["steps"][0].update(cypher=t["steps"][0]["cypher"].replace("tenant_id", "tid")))
    with pytest.raises(OntologyLoadError, match="tenant_id"):
        load_ontology(onto, PINS, allow_reference_only=True)


def test_loader_rejects_a_missing_file_and_a_wrong_prefix(onto):
    pm = app_pack(onto) / "pack.yml"
    pm.write_text(pm.read_text(encoding="utf-8") + "    - templates/nope.yml\n", encoding="utf-8")
    with pytest.raises(OntologyLoadError, match="template file missing"):
        load_ontology(onto, PINS, allow_reference_only=True)
    (app_pack(onto) / "templates/nope.yml").write_text((app_pack(onto) / "templates/app_documents_of.yml").read_text(), encoding="utf-8")
    with pytest.raises(OntologyLoadError, match="must start with app_"):
        load_ontology(onto, PINS, allow_reference_only=True)


def test_ci_rejects_core_name_unlisted_file_and_unknown_relationship(onto):
    shutil.copy(app_pack(onto) / "templates/app_documents_of.yml", app_pack(onto) / "templates/owner_of.yml")
    assert any("not listed" in e for e in ci_errors(onto))
    pm = app_pack(onto) / "pack.yml"
    pm.write_text(pm.read_text(encoding="utf-8") + "    - templates/owner_of.yml\n", encoding="utf-8")
    errs = ci_errors(onto)
    assert any("start with app_" in e for e in errs) and any("reuses a core template name" in e for e in errs)
    edit_template(onto, "app_documents_of", lambda t: t["steps"][0].update(cypher=t["steps"][0]["cypher"].replace("[r:documents]", "[r:adores]")))
    assert any("unknown relationship type adores" in e for e in ci_errors(onto))


def test_ci_rejects_a_pack_template_that_is_too_deep_or_has_no_limit(onto):
    edit_template(onto, "app_references_of", lambda t: t.update(limits={"max_depth": 5, "fanout_cap": 500}))
    errs = ci_errors(onto)
    assert any("max_depth above" in e for e in errs) and any("fanout_cap above" in e for e in errs)
    edit_template(onto, "app_references_of", lambda t: t["steps"][0].update(cypher=t["steps"][0]["cypher"].replace("LIMIT $fanout_cap", "")))
    assert any("no LIMIT" in e for e in ci_errors(onto))
