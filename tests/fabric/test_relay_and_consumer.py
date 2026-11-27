import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fake_s3 import FakeS3

from tests.fabric.helpers import edge, node, ref, retraction
from usep.adapters.s3.event_bus import S3EventBus
from usep.fabric import FabricConsumer, FabricWriter, OutboxRelay
from usep.fabric.topics import register_commit_schemas
from usep.pipeline.topics import register_schemas
from usep.ports.event_bus import SchemaRegistry


def make_bus():
    reg = SchemaRegistry()
    register_schemas(reg, ("engineering",))
    register_commit_schemas(reg)
    return S3EventBus(FakeS3(), "b", reg, partitions=4)


class FlakyBus:
    """Fails the Nth publish; records what it accepted."""

    def __init__(self, fail_on=()):
        self.fail_on, self.n, self.got = set(fail_on), 0, []

    def publish(self, topic, key, type, tenant_id, payload, headers=None):
        self.n += 1
        if self.n in self.fail_on:
            raise ConnectionError("bus down")
        self.got.append((topic, type, payload["idempotency_key"]))


def test_relay_publishes_in_commit_order_and_marks_done(store):
    w, bus = FabricWriter(store), FlakyBus()
    w.handle(node(sid="A-1")); w.handle(node(sid="A-2")); w.handle(edge(ref("A-1"), ref("A-2")))
    res = OutboxRelay(store, bus).run_once()
    assert (res.published, res.failed) == (3, 0)
    assert [g[1] for g in bus.got] == ["entity.committed", "entity.committed", "edge.committed"]
    assert [g[2] for g in bus.got] == ["outbox-1", "outbox-2", "outbox-3"]
    assert OutboxRelay(store, bus).run_once().published == 0 and store.outbox_status().pending == 0


def test_relay_stops_at_a_failure_keeps_order_and_retries_later(store):
    w = FabricWriter(store)
    for i in range(3):
        w.handle(node(sid=f"A-{i}"))
    bus = FlakyBus(fail_on={2})
    res = OutboxRelay(store, bus).run_once()
    assert (res.published, res.failed) == (1, 1) and store.outbox_status().pending == 2
    res = OutboxRelay(store, bus).run_once()                      # the bus is back
    assert res.published == 2 and [g[2] for g in bus.got] == ["outbox-1", "outbox-2", "outbox-3"]


def test_a_row_that_keeps_failing_goes_dead_and_is_counted_not_retried(store):
    FabricWriter(store).handle(node(sid="A-1"))
    FabricWriter(store).handle(node(sid="A-2"))
    bus = FlakyBus(fail_on={1, 2, 3})
    relay = OutboxRelay(store, bus, max_attempts=3)
    for _ in range(3):
        relay.run_once()
    st = store.outbox_status()
    assert st.dead == 1 and st.pending == 1                       # row 1 is dead, row 2 is not blocked by it
    assert relay.run_once().published == 1 and store.outbox_status().pending == 0


def test_status_reports_pending_and_age(store):
    assert store.outbox_status().pending == 0 and store.outbox_status().oldest_pending_seconds is None
    FabricWriter(store).handle(node())
    st = store.outbox_status()
    assert st.pending == 1 and st.oldest_pending_seconds is not None and st.last_outbox_id == 1


def test_consumer_end_to_end_through_the_s3_bus(store):
    bus = make_bus()
    for e in (node(sid="A-1"), node(sid="A-2"), edge(ref("A-1"), ref("A-2")), retraction("A-2")):
        bus.publish(e.topic, e.payload.get("attributes", {}).get("source_id", "k") if e.topic != "retraction" else "A-2",
                    e.type, e.tenant_id, e.payload)
    c = FabricConsumer(bus, FabricWriter(store), ("engineering",))
    assert c.run_once() == 4 and c.run_once() == 0                # offsets committed: nothing is read twice
    OutboxRelay(store, bus).drain()
    got = [d.event.type for d in bus.poll("commit.entity", "projector", 100)] + \
          [d.event.type for d in bus.poll("commit.edge", "projector", 100)]
    assert sorted(got) == ["edge.committed", "edge.retracted", "entity.committed", "entity.committed", "entity.retracted"]


def test_replaying_the_same_events_after_an_offset_reset_changes_nothing(store):
    bus = make_bus()
    e = node()
    bus.publish(e.topic, "ABC-1", e.type, e.tenant_id, e.payload)
    c = FabricConsumer(bus, FabricWriter(store), ("engineering",))
    c.run_once()
    bus.reset("entity.engineering", "fabric-writer")
    assert c.run_once() == 1 and store.outbox_status().last_outbox_id == 1
