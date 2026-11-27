"""Look at what has landed: list recent raw objects, or decrypt one and print it.

    python -m tools.read_raw                 # list the latest objects
    python -m tools.read_raw <object_key>    # decrypt and print one

Decrypting needs the key-encryption key, so it works only where the service itself runs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from uuid import UUID

from sqlalchemy import select

from config import get_settings
from db.base import create_engine, create_session_factory
from db.models import RawObjectRow
from db.ports_sql import SqlRawIndex
from raw_store import make_object_store
from usep.adapters.local_kek.key_store import LocalKeyEncryption
from usep.ingestion.ports.object_store import ObjectStorePort
from usep.ingestion.raw.crypto import decrypt, unpack


async def read_raw_object(
    index: SqlRawIndex, store: ObjectStorePort, keys: LocalKeyEncryption, tenant_id: UUID, object_key: str
) -> dict:
    """Decrypt one stored object with the data key from its index row."""
    ref = next((r for r in await index.list_by_key(tenant_id, object_key)), None)
    if ref is None or ref.wrapped_dek is None:
        raise LookupError(f"no readable raw object with key {object_key!r} (unknown, or erased)")
    data_key = await keys.unwrap(tenant_id, ref.wrapped_dek, ref.kek_id)
    aad = object_key.encode() + str(tenant_id).encode()
    return json.loads(decrypt(unpack(await store.get(object_key)), data_key, aad=aad))


async def _main(argv: list[str]) -> int:
    settings = get_settings()
    if not settings.tenant_id:
        print("USEP_INGESTION_TENANT_ID is not set", file=sys.stderr)
        return 2
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        if not argv:
            async with session_factory() as session:
                rows = await session.scalars(
                    select(RawObjectRow)
                    .where(RawObjectRow.tenant_id == settings.tenant_id)
                    .order_by(RawObjectRow.imported_at.desc())
                    .limit(20)
                )
                for row in rows:
                    print(f"{row.imported_at:%Y-%m-%d %H:%M:%S}  {row.source:<10} {row.object_id:<24} {row.object_key}")
            return 0
        store = make_object_store(settings)
        keys = LocalKeyEncryption(base64.b64decode(settings.dev_kek_b64))
        print(json.dumps(await read_raw_object(SqlRawIndex(session_factory), store, keys, settings.tenant_id, argv[0]), indent=2))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
