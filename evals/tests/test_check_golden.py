"""The golden set checker passes the real file and rejects each kind of bad input."""
import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_golden as cg  # noqa: E402

REAL = ROOT / "golden" / "golden_set_engineering.yaml"


def errors_after(tmp_path, mutate):
    doc = yaml.safe_load(REAL.read_text(encoding="utf-8"))
    mutate(doc["items"])
    p = tmp_path / "golden_set_engineering.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return cg.check(p)


def test_real_file_passes(tmp_path):
    assert cg.check(REAL) == []


def test_duplicate_question_fails(tmp_path):
    def m(items):
        items[1]["question"] = items[0]["question"]
    assert any("same question" in e for e in errors_after(tmp_path, m))


def test_unknown_template_fails(tmp_path):
    def m(items):
        items[0]["template"] = "befriend@1.0"
    assert any("not in ontology/templates" in e for e in errors_after(tmp_path, m))


def test_gap_in_ids_fails(tmp_path):
    def m(items):
        del items[5]
    assert any("no gaps" in e for e in errors_after(tmp_path, m))


def test_missing_field_fails(tmp_path):
    def m(items):
        del items[0]["sme_owner"]
    assert any("fields must be exactly" in e for e in errors_after(tmp_path, m))


def test_empty_evidence_fails(tmp_path):
    def m(items):
        items[0]["required_evidence"] = []
    assert any("required_evidence is empty" in e for e in errors_after(tmp_path, m))


def test_unknown_source_system_fails(tmp_path):
    def m(items):
        items[0]["required_evidence"] = [{"source_system": "sharepoint", "source_id": "x"}]
    assert any("source_system" in e for e in errors_after(tmp_path, m))


def test_below_floor_fails(tmp_path):
    def m(items):
        del items[149:]
    assert any("floor is 150" in e for e in errors_after(tmp_path, m))


def test_too_few_permission_aware_items_fails(tmp_path):
    def m(items):
        for it in items:
            it["must_not_include"] = []
    assert any("permission-aware" in e for e in errors_after(tmp_path, m))


def test_repeated_claim_fails(tmp_path):
    def m(items):
        items[1]["expected_claims"] = copy.deepcopy(items[0]["expected_claims"])
    assert any("claim repeated" in e for e in errors_after(tmp_path, m))
