import pytest

from tests.fake_s3 import FakeS3
from tests.pipeline.helpers import BUCKET, ONT, PINS
from usep.adapters.s3.event_bus import S3EventBus
from usep.adapters.s3.snapshot_store import S3SnapshotStore
from usep.ontology import load_ontology
from usep.pipeline.topics import register_schemas
from usep.pipeline.worker import AcquisitionWorker
from usep.ports.event_bus import SchemaRegistry


@pytest.fixture(scope="module")
def bundle():
    return load_ontology(ONT, PINS, allow_reference_only=True)


@pytest.fixture
def env(bundle):
    """(fake S3, bus, worker) over the reference packs."""
    s3 = FakeS3()
    reg = SchemaRegistry()
    register_schemas(reg, bundle.domains)
    bus = S3EventBus(s3, BUCKET, reg, partitions=4)
    worker = AcquisitionWorker(bus, S3SnapshotStore(s3, BUCKET), lambda: bundle)
    return s3, bus, worker
