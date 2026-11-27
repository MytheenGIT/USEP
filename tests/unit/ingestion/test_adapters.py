from __future__ import annotations

import os
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws

from usep.adapters.local_kek.key_store import LocalKeyEncryption
from usep.adapters.s3.object_store import S3ObjectStore
from usep.core.errors import ConfigError


@pytest.mark.asyncio
async def test_s3_object_store_round_trip_and_exists() -> None:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="raw")
        store = S3ObjectStore(client, "raw")

        assert not await store.exists("a/b.json")
        await store.put("a/b.json", b"cipher")
        assert await store.exists("a/b.json")
        assert await store.get("a/b.json") == b"cipher"


@pytest.mark.asyncio
async def test_local_key_wrap_round_trip_and_tenant_binding() -> None:
    keys = LocalKeyEncryption(os.urandom(32))
    tenant, other = uuid4(), uuid4()
    data_key = os.urandom(32)

    wrapped, kek_id = await keys.wrap(tenant, data_key)

    assert wrapped != data_key
    assert await keys.unwrap(tenant, wrapped, kek_id) == data_key
    with pytest.raises(Exception):  # noqa: B017 - another tenant's id must not unwrap it
        await keys.unwrap(other, wrapped, kek_id)


def test_local_key_must_be_32_bytes() -> None:
    with pytest.raises(ConfigError):
        LocalKeyEncryption(b"short")


@pytest.mark.asyncio
async def test_check_refuses_a_bucket_that_cannot_be_used() -> None:
    with mock_aws():
        store = S3ObjectStore(boto3.client("s3", region_name="us-east-1"), "no-such-bucket")
        with pytest.raises(ConfigError) as caught:
            await store.check()
    assert "no-such-bucket" in str(caught.value)


@pytest.mark.asyncio
async def test_check_warns_when_write_once_protection_is_missing_and_not_when_present() -> None:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="plain")
        warnings = await S3ObjectStore(client, "plain").check()
        assert "bucket versioning is not enabled" in warnings and "object lock is not configured" in warnings

        client.create_bucket(Bucket="locked", ObjectLockEnabledForBucket=True)
        client.put_bucket_versioning(Bucket="locked", VersioningConfiguration={"Status": "Enabled"})
        assert await S3ObjectStore(client, "locked").check() == []


@pytest.mark.asyncio
async def test_file_store_round_trip_matches_the_s3_contract(tmp_path) -> None:
    from usep.adapters.local_files.object_store import FileObjectStore

    store = FileObjectStore(tmp_path / "raw")
    key = "raw/t/jira/ENG/issue/ABC-1/abc.json"

    assert not await store.exists(key)
    await store.put(key, b"cipher")
    await store.put(key, b"cipher-2")  # overwrite is allowed, as on S3
    assert await store.exists(key) and await store.get(key) == b"cipher-2"
    assert [p.name for p in (tmp_path / "raw" / "raw/t/jira/ENG/issue/ABC-1").iterdir()] == ["abc.json"]  # no temp files left
    assert await store.check() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["../escape", "raw/../../escape", "/etc/passwd", "raw//x", "", "raw/./x", "a\0b"])
async def test_file_store_refuses_keys_that_could_leave_its_folder(tmp_path, key) -> None:
    from usep.adapters.local_files.object_store import FileObjectStore

    store = FileObjectStore(tmp_path / "raw")
    with pytest.raises(ValueError):
        await store.put(key, b"x")
    assert list(tmp_path.rglob("escape")) == []
