import pytest

from tests.fabric.helpers import T, edge, node, ref, retraction
from usep.fabric import FabricWriter


def outbox_types(store):
    out = []
    with store.claim_outbox(1000, 5) as b:
        out = [(r.topic, r.type) for r in b.rows]
    return out


def rows(store, tenant=T):
    """(row_version, sensitivity, retracted, attributes) of every entity state, from either store."""
    if hasattr(store, "states"):
        return [(s.row_version, int(s.labels.get("sensitivity") or 0), s.retracted, dict(s.attributes))
                for s in store.states(tenant)]
    with store._connect() as c:
        return [(r["row_version"], r["sensitivity"], r["retracted_at"] is not None, r["attributes"]) for r in c.execute(
            "SELECT * FROM fabric_entity_state WHERE tenant_id=%s ORDER BY updated_at", (tenant,)).fetchall()]


def assertions(store, tenant=T):
    if hasattr(store, "d"):
        return [(a.subject_kind, a.applied, a.reason) for t, a in store.d.assertions if t == tenant]
    with store._connect() as c:
        return [(r["subject_kind"], r["applied"], r["reason"]) for r in c.execute(
            "SELECT * FROM fabric_assertion WHERE tenant_id=%s ORDER BY recorded_at, assertion_id", (tenant,)).fetchall()]


def rejected(store, tenant=T):
    if hasattr(store, "d"):
        return [v[1] for (t, _), v in store.d.rejected.items() if t == tenant]
    with store._connect() as c:
        return [r["code"] for r in c.execute("SELECT code FROM fabric_rejected WHERE tenant_id=%s", (tenant,)).fetchall()]


def edges(store, tenant=T):
    if hasattr(store, "d"):
        return [(e.pending, e.retracted, e.row_version) for (t, _), e in store.d.edges.items() if t == tenant]
    with store._connect() as c:
        return [(r["from_entity_id"] is None or r["to_entity_id"] is None, r["retracted"], r["row_version"])
                for r in c.execute("SELECT * FROM fabric_edge WHERE tenant_id=%s", (tenant,)).fetchall()]


@pytest.fixture
def w(store):
    return FabricWriter(store)


def test_node_commits_state_history_and_outbox(w, store):
    r = w.handle(node())
    assert r.status == "committed" and r.outbox == 1
    assert rows(store) == [(1, 1, False, {"source_system": "jira", "source_id": "ABC-1", "source_version": "1",
                                          "valid_from": "2026-01-01T00:00:00Z", "name": "n"})]
    assert assertions(store) == [("node", True, "")]
    assert outbox_types(store) == [("commit.entity", "entity.committed")]


def test_duplicate_event_changes_nothing(w, store):
    e = node()
    assert w.handle(e).status == "committed"
    assert w.handle(e).status == "duplicate"
    assert len(rows(store)) == 1 and len(outbox_types(store)) == 1 and len(assertions(store)) == 1


def test_newer_replaces_and_stale_is_kept_as_history_only(w, store):
    w.handle(node(valid_from="2026-03-01T00:00:00Z", version="2", name="new"))
    r = w.handle(node(valid_from="2026-01-01T00:00:00Z", version="1", name="old"))
    assert r.status == "stale"
    (rv, _, _, attrs), = rows(store)
    assert rv == 1 and attrs["name"] == "new"
    assert assertions(store) == [("node", True, ""), ("node", False, "stale")]
    r = w.handle(node(valid_from="2026-04-01T00:00:00Z", version="3", name="newest"))
    assert r.status == "committed" and rows(store)[0][0] == 2 and rows(store)[0][3]["name"] == "newest"


def test_equal_version_is_not_a_change(w, store):
    w.handle(node(key="k1"))
    assert w.handle(node(key="k2")).status == "stale"           # same event time and version, new delivery
    assert rows(store)[0][0] == 1


def test_sensitivity_never_goes_down(w, store):
    w.handle(node(sens=3, valid_from="2026-01-01T00:00:00Z"))
    w.handle(node(sens=1, valid_from="2026-02-01T00:00:00Z", version="2"))
    (rv, sens, _, _), = rows(store)
    assert rv == 2 and sens == 3


def test_type_conflict_is_parked_and_state_is_unchanged(w, store):
    w.handle(node(type="Issue"))
    r = w.handle(node(type="Service", valid_from="2026-05-01T00:00:00Z", version="9"))
    assert r.status == "rejected" and r.detail == "type_conflict"
    assert rejected(store) == ["type_conflict"] and len(rows(store)) == 1 and rows(store)[0][0] == 1
    assert w.handle(node(sid="ABC-2")).status == "committed"    # the consumer is not stuck


@pytest.mark.parametrize("mutate", [lambda p: p["attributes"].pop("source_id"), lambda p: p.pop("type"),
                                    lambda p: p["attributes"].update(valid_from="not a date")])
def test_malformed_events_are_parked(w, store, mutate):
    e = node()
    mutate(e.payload)                                             # payload is a plain dict
    assert w.handle(e).status == "rejected" and len(rows(store)) == 0 and len(rejected(store)) == 1


def test_edge_between_known_entities_commits(w, store):
    w.handle(node(sid="A-1")); w.handle(node(sid="A-2"))
    r = w.handle(edge(ref("A-1"), ref("A-2")))
    assert r.status == "committed" and edges(store) == [(False, False, 1)]
    assert ("commit.edge", "edge.committed") in outbox_types(store)


def test_pending_edge_is_linked_when_the_missing_node_commits(w, store):
    w.handle(node(sid="A-1"))
    assert w.handle(edge(ref("A-1"), ref("A-2"))).status == "pending"
    assert edges(store) == [(True, False, 1)]
    before = len(outbox_types(store))
    w.handle(node(sid="A-2"))
    assert edges(store) == [(False, False, 2)]
    assert len(outbox_types(store)) == before + 2               # the node and the newly linked edge


def test_typed_end_that_does_not_match_stays_pending(w, store):
    w.handle(edge(ref("A-1"), ref("S-1", "git", "Service")))
    w.handle(node(sid="A-1"))
    w.handle(node(sid="S-1", system="git", type="Issue"))       # a git Issue is not the Service the edge names
    assert edges(store)[0][0] is True


def test_edge_to_an_entity_of_the_wrong_type_is_rejected(w, store):
    w.handle(node(sid="A-1")); w.handle(node(sid="S-1", system="git", type="Issue"))
    r = w.handle(edge(ref("A-1"), ref("S-1", "git", "Service")))
    assert r.status == "rejected" and r.detail == "type_conflict" and edges(store) == []


def test_retraction_marks_state_and_edges_and_blocks_stale_revival(w, store):
    w.handle(node(sid="A-1")); w.handle(node(sid="A-2")); w.handle(edge(ref("A-1"), ref("A-2")))
    r = w.handle(retraction("A-1", at="2026-02-01T00:00:00Z"))
    assert r.status == "retracted" and r.extra == {"entities": 1, "edges": 1}
    assert edges(store) == [(False, True, 2)]
    assert [x[2] for x in rows(store)].count(True) == 1
    types = outbox_types(store)
    assert ("commit.entity", "entity.retracted") in types and ("commit.edge", "edge.retracted") in types
    assert w.handle(node(sid="A-1", valid_from="2026-01-15T00:00:00Z", version="2")).status == "stale"
    assert w.handle(node(sid="A-1", valid_from="2026-03-01T00:00:00Z", version="3")).status == "committed"
    assert not [x for x in rows(store) if x[3]["source_id"] == "A-1"][0][2]


def test_retraction_twice_is_idempotent(w, store):
    w.handle(node())
    r = retraction()
    assert w.handle(r).status == "retracted" and w.handle(r).status == "duplicate"
    assert w.handle(retraction(key="other")).extra == {"entities": 0, "edges": 0}


def test_tenants_do_not_share_identity_or_history(w, store):
    w.handle(node(tenant="t1")); w.handle(node(tenant="t2"))
    assert len(rows(store, "t1")) == 1 and len(rows(store, "t2")) == 1
    w.handle(retraction(tenant="t1"))
    assert rows(store, "t1")[0][2] is True and rows(store, "t2")[0][2] is False


def test_failure_inside_the_commit_rolls_everything_back_and_a_retry_succeeds(w, store):
    real = store.transaction

    class Boom(Exception):
        pass

    from contextlib import contextmanager

    @contextmanager
    def failing(tenant):
        with real(tenant) as tx:
            def bad(*a, **k):
                raise Boom()
            tx.enqueue = bad
            yield tx

    store.transaction = failing
    with pytest.raises(Boom):
        w.handle(node())
    store.transaction = real
    assert rows(store) == [] and assertions(store) == [] and outbox_types(store) == []
    assert w.handle(node()).status == "committed"                # the idempotency claim was rolled back too
