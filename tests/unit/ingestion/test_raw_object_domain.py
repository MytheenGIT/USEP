from __future__ import annotations

from uuid import uuid4

import pytest

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


def test_keys_do_not_collide_when_a_part_contains_a_slash() -> None:
    first = object_key(TENANT, "gitlab", "g/p", "blob", "x", "h")
    second = object_key(TENANT, "gitlab", "g", "p", "blob/x", "h")

    assert first != second


def test_plain_parts_keep_the_documented_key_layout() -> None:
    assert object_key(TENANT, "jira", "PROJ", "issue", "PROJ-1", "abc") == (
        f"raw/{TENANT}/jira/PROJ/issue/PROJ-1/abc.json"
    )


@pytest.mark.parametrize("dots", [".", ".."])
def test_a_part_made_only_of_dots_cannot_act_as_a_path_step(dots: str) -> None:
    key = object_key(TENANT, "jira", "PROJ", "issue", dots, "abc")

    assert f"/{dots}/" not in key


@pytest.mark.parametrize("empty_part", [0, 1, 2, 3])
def test_empty_key_part_is_rejected(empty_part: int) -> None:
    parts = ["jira", "PROJ", "issue", "PROJ-1"]
    parts[empty_part] = ""

    with pytest.raises(ValueError, match="non-empty"):
        object_key(TENANT, parts[0], parts[1], parts[2], parts[3], "abc")
