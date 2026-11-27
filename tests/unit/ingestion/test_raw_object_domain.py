from __future__ import annotations

from uuid import uuid4

from usep.ingestion.domain.raw_object import canonicalize, content_hash, object_key

TENANT = uuid4()


def test_canonicalize_is_deterministic_regardless_of_key_order() -> None:
    a = canonicalize({"b": 1, "a": 2})
    b = canonicalize({"a": 2, "b": 1})
    assert a == b
    assert a == b'{"a":2,"b":1}'


def test_content_hash_changes_when_payload_changes() -> None:
    h1 = content_hash(canonicalize({"a": 1}))
    h2 = content_hash(canonicalize({"a": 2}))
    assert h1 != h2
    assert len(h1) == 64  # sha256 hex


def test_object_key_has_no_run_id_and_is_stable_across_runs() -> None:
    """D11: the same (tenant, source, scope, type, id, hash) always resolves to the
    same key, regardless of which run produced it — fixes the PoC's run_id-in-key bug."""
    key1 = object_key(TENANT, "jira", "PROJ", "issue", "PROJ-1", "deadbeef")
    key2 = object_key(TENANT, "jira", "PROJ", "issue", "PROJ-1", "deadbeef")
    assert key1 == key2
    assert "run_id" not in key1
    assert key1 == f"raw/{TENANT}/jira/PROJ/issue/PROJ-1/deadbeef.json"


def test_object_key_changes_when_content_hash_changes() -> None:
    key1 = object_key(TENANT, "jira", "PROJ", "issue", "PROJ-1", "hash1")
    key2 = object_key(TENANT, "jira", "PROJ", "issue", "PROJ-1", "hash2")
    assert key1 != key2
