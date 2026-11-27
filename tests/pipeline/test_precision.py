from usep.pipeline import precision as pr


def ev(i, rel="references", method="rule"):
    return {"payload": {"kind": "edge", "type": rel, "idempotency_key": f"k{i}", "provenance": {"method": method, "rule": "r"},
                        "from": {"source_system": "jira", "source_id": f"A-{i}"}, "to": {"source_system": "jira", "source_id": "B-1"},
                        "attributes": {"confidence": 0.9}}}


def test_sample_caps_per_relation_is_repeatable_dedupes_and_keeps_rare_method():
    events = [ev(i) for i in range(150)] + [ev(i + 500, method="api_link") for i in range(3)] + [ev(1)] + [ev(900, "documents")]
    rows = pr.edge_rows(events)
    assert len(rows) == 154
    s = pr.sample(rows, 100)
    assert s == pr.sample(rows, 100)
    assert sum(r["relation"] == "references" for r in s) == 100 and sum(r["relation"] == "documents" for r in s) == 1
    assert sum(r["method"] == "api_link" for r in s) == 3


def test_score_uses_reviewed_rows_only(tmp_path):
    rows = pr.edge_rows([ev(i) for i in range(4)] + [ev(9, method="api_link")])
    for r, lab in zip(rows, ["y", "y", "n", "", "y"]):
        r["label"] = lab
    f = tmp_path / "s.csv"
    pr.write_sheet(rows, f)
    out = pr.score(f)
    assert out["references"] == {"reviewed": 4, "correct": 3, "precision": 0.75}
    assert out["references/api_link"]["precision"] == 1.0
