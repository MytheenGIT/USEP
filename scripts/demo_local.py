#!/usr/bin/env python3
"""Run the whole ingestion flow locally on dummy data. No AWS, no network, no secrets.

    python scripts/demo_local.py                 # summary
    python scripts/demo_local.py --show          # also print every entity / quarantine event
    python scripts/demo_local.py --out demo_out  # dump every object the flow wrote (raw/, bus/, evidence/, quarantine/)
    python scripts/demo_local.py --only jira     # one source

What runs for real: the connector Lambda path (SyncService, S3 snapshot writer, S3 event publisher, cursor) with a
stand-in connector that returns the dummy payloads, then the pipeline Lambda path (poll mode), over an in-memory S3.
What is faked: the source APIs and S3 itself. Payloads: scripts/sample_data/dummy.json. Each record says what it should do.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "services" / "connectors")]

import importlib.util  # noqa: E402
import logging  # noqa: E402

import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))   # quiet the sync logs

_spec = importlib.util.spec_from_file_location("repo_fake_s3", ROOT / "tests" / "fake_s3.py")   # not the connectors' own
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
FakeS3 = _mod.FakeS3

import lambda_handler as lh  # noqa: E402  (services/connectors)
from common.connector_base import ScopeFetch  # noqa: E402
from common.source_document import SourceDocument, SourceType  # noqa: E402
from config import Settings  # noqa: E402
from usep.adapters.aws_lambda import pipeline_handler as ph  # noqa: E402
from usep.core.ids import uuid7  # noqa: E402
from usep.ontology_runtime import load_ontology  # noqa: E402

TENANT, BUCKET = str(uuid7()), "demo"
PINS = ["app.app-reference@0.1.0", "org.org-reference@0.1.0", "project.project-reference@0.1.0"]


class StandIn:
    """A connector that returns dummy payloads instead of calling a source API."""

    def __init__(self, source: str, items: list[dict]) -> None:
        self.source, self._items = SourceType(source), items

    @property
    def scopes(self) -> list[str]:
        return ["demo"]

    async def fetch_scope(self, scope, cursor):
        docs = [SourceDocument(source=self.source, source_type="dummy", source_object_id=i["id"], scope=scope,
                               source_version="2026-01-01T00:00:00.000Z", acl=i.get("acl", {}),
                               source_url=f"https://dummy.invalid/{i['id']}", retrieved_at=datetime.now(UTC),
                               raw_payload=i["raw"], title=i["id"]) for i in self._items]
        return ScopeFetch(documents=docs)


class NoClient:
    async def aclose(self) -> None:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--only")
    args = ap.parse_args()

    data = {k: v for k, v in json.loads((ROOT / "scripts/sample_data/dummy.json").read_text()).items() if not k.startswith("_")}
    if args.only:
        data = {args.only: data[args.only]}
    s3 = FakeS3()

    # ---- stage 1: connectors (the Lambda code path)
    settings = Settings(tenant_id=TENANT, s3={"bucket": BUCKET, "bus_partitions": 4})
    print("== C-01 connectors ==")
    for source, items in data.items():
        res = asyncio.run(lh.run(source, settings, s3, lambda s, _st, items=items: (NoClient(), StandIn(s, items))))
        print(f"  {source:<11} {res['documents']} documents -> raw snapshots + raw.{source} events")

    # ---- stage 2: pipeline (poll mode drains raw.<family> from offsets)
    import os
    os.environ.update({"USEP_BUS_BUCKET": BUCKET, "USEP_BUS_PARTITIONS": "4", "USEP_TENANT_ID": TENANT,
                       "USEP_REPO_HOSTS": "gitlab.example.com"})
    ph._state.clear()
    ph._injected.clear()
    loader = lambda pins: load_ontology(ROOT / "ontology", pins or PINS, allow_reference_only=True)
    os.environ["USEP_ONTOLOGY_PINS"] = ",".join(PINS)
    out = ph.handler({"poll": True, "limit": 1000}, _s3=s3, _loader=loader)
    print("\n== C-02 pipeline ==")
    print(f"  handled {out['handled']} raw events | entities {out['entities']} | edges {out['edges']} | "
          f"link edges {out['links']} | evidence-only {out['evidence_only']} | quarantined {out['quarantined']}")
    print(f"  ontology {out['ontology_digest'][:12]}")

    # ---- results
    events = {}
    for k, v in sorted(s3.objects.items()):
        if k.startswith("bus/") and not k.startswith(("bus/raw.", "bus/_offsets")):
            e = json.loads(v)
            events.setdefault(e["topic"], []).append(e)
    print("\n== published events ==")
    for topic, evs in events.items():
        print(f"  {topic:<22} {len(evs)}")
    reasons = Counter(e["payload"]["reason_code"] for e in events.get("quarantine", []))
    if reasons:
        print("  quarantine reasons:", dict(sorted(reasons.items())))
    print("\n== what each dummy record was expected to do ==")
    for source, items in data.items():
        for i in items:
            print(f"  {source}/{i['id']}: {i['expect']}")

    ev_events = [e for t, evs in events.items() if t.startswith("evidence.") for e in evs]
    if ev_events:
        allowed = sum(1 for e in ev_events if e["payload"]["egress"]["external_model"])
        blocked = Counter(r for e in ev_events for r in e["payload"]["egress"]["reasons"])
        print(f"\n== evidence for chunking and LLM teams ==\n  {len(ev_events)} evidence objects | "
              f"external model allowed {allowed} | blocked {len(ev_events) - allowed} {dict(sorted(blocked.items()))}")

    if args.show:
        print("\n== entity and quarantine events ==")
        for topic, evs in events.items():
            for e in evs:
                p = e["payload"]
                if topic.startswith("evidence."):
                    print(f"  [{topic}] {p['source_system']}/{p['source_id']} sens={p['sensitivity']} "
                          f"acl={p['acl_state']} scopes={p['acl']['scopes']} egress={p['egress']['external_model']}")
                    continue
                if topic == "quarantine":
                    print(f"  [{topic}] {p['source_system']}/{p['source_ref']} {p['reason_code']}: {p['reason']}")
                else:
                    a = p["attributes"]
                    who = a.get("source_id") or f"{p['from']['source_id']} -> {p['to'].get('source_id') or p['to'].get('repository_ref')}"
                    extra = f" prov={p['provenance']['rule']} conf={a['confidence']}" if "provenance" in p else \
                        f" sens={p['labels']['sensitivity']} acl={p['labels']['acl_state']}"
                    print(f"  [{topic}] {p['kind']} {p['type']} {who}{extra}")
    if args.out:
        for k, v in s3.objects.items():
            path = Path(args.out) / k
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(v)
        print(f"\nwrote {len(s3.objects)} objects under {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
