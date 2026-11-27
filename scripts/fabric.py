"""Fabric writer command line (C-04, ADR-21). Run from the repository root.

  migrate  --dsn DSN                              apply the SQL migrations
  write    --dsn DSN --bucket B [--domains a,b]   commit what is waiting on entity.<domain> and retraction
  relay    --dsn DSN --bucket B [--batch N]       publish committed changes from the outbox to commit.entity / commit.edge
  status   --dsn DSN                              outbox pending, dead and oldest age

DSN may come from the USEP_FABRIC_DSN environment variable. Never put a password on the command line in a shared shell:
use a DSN from the secrets manager. `write` and `relay` run once and exit; schedule them (or loop) in the deployment.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("migrate", "write", "relay", "status"):
        p = sub.add_parser(name)
        p.add_argument("--dsn", default=os.environ.get("USEP_FABRIC_DSN"))
        if name in ("write", "relay"):
            p.add_argument("--bucket", default=os.environ.get("USEP_BUS_BUCKET"))
            p.add_argument("--prefix", default="bus")
        if name == "write":
            p.add_argument("--domains", default="engineering")
        if name == "relay":
            p.add_argument("--batch", type=int, default=100)
    a = ap.parse_args()
    if not a.dsn:
        sys.exit("give --dsn or set USEP_FABRIC_DSN")

    import psycopg

    from usep.adapters.postgres import PostgresFabricStore, migrate
    if a.cmd == "migrate":
        with psycopg.connect(a.dsn) as c:
            print(json.dumps({"applied": migrate(c)}))
        return 0
    store = PostgresFabricStore(a.dsn)
    if a.cmd == "status":
        print(json.dumps(store.outbox_status().__dict__))
        return 0
    if not a.bucket:
        sys.exit("give --bucket or set USEP_BUS_BUCKET")
    import boto3

    from usep.adapters.s3.event_bus import S3EventBus
    from usep.fabric import FabricConsumer, FabricWriter, OutboxRelay
    from usep.fabric.topics import register_commit_schemas
    from usep.pipeline.topics import register_schemas
    from usep.ports.event_bus import SchemaRegistry
    domains = tuple(d for d in getattr(a, "domains", "engineering").split(",") if d)
    reg = SchemaRegistry()
    register_schemas(reg, domains)
    register_commit_schemas(reg)
    bus = S3EventBus(boto3.client("s3"), a.bucket, reg, a.prefix)
    if a.cmd == "write":
        print(json.dumps({"handled": FabricConsumer(bus, FabricWriter(store), domains).run_once()}))
    else:
        r = OutboxRelay(store, bus, a.batch).drain()
        print(json.dumps({"published": r.published, "failed": r.failed}))
        return 1 if r.failed else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
