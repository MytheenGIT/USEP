"""The join between source fields, core attributes and project-pack tables must stay consistent in three places:
pipeline/state_tables.py, the project pack's workflow.yml, and the pack check's WORKFLOW_TABLES."""
import sys

import yaml

from tests.pipeline.helpers import ONT
from usep.pipeline.state_tables import STATE_TABLES

sys.path.insert(0, str(ONT / "tools"))
import check_ontology as co  # noqa: E402


def test_every_state_table_is_in_the_reference_workflow_and_the_pack_check():
    wf = yaml.safe_load((ONT / "packs/project/project-reference/workflow.yml").read_text(encoding="utf-8"))
    for _system, _concept, attr, _field, table in STATE_TABLES:
        assert table in wf, f"{table} missing from the project pack"
        assert co.WORKFLOW_TABLES[table][0] == attr, f"{table}: pack check expects a different attribute"


def test_pack_check_knows_no_table_the_pipeline_ignores():
    assert set(co.WORKFLOW_TABLES) == {t for *_, t in STATE_TABLES}
