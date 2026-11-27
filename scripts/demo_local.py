#!/usr/bin/env python3
"""Run the whole ingestion flow locally on dummy data. No AWS, no network, no secrets.

    python scripts/demo_local.py                 # summary
    python scripts/demo_local.py --show          # also print every entity / quarantine event
    python scripts/demo_local.py --out demo_out  # dump every object the flow wrote (raw/, bus/, evidence/, quarantine/)
    python scripts/demo_local.py --only jira     # one source

What runs for real: the pipeline Lambda path (poll mode: normalize, redact, classify, map, gate G1, link, evidence), over an
in-memory S3. What is stand-in: the connectors' output. The dummy payloads are landed by the S3 snapshot writer and raw event
publisher (snapshot first, then an event that only references it); no source API is called, and `main`'s encrypted raw writer
(usep.ingestion) is not in this path. Payloads: scripts/sample_data/dummy.json. Each record says what it should do.
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

from common.checksum import payload_checksum  # noqa: E402  (services/connectors)
from common.interfaces.raw_event_publisher import RawEvent  # noqa: E402
from common.s3.raw_event_publisher import S3RawEventPublisher  # noqa: E402
from common.s3.raw_payload_writer import S3RawPayloadWriter  # noqa: E402
from usep.adapters.aws_lambda import pipeline_handler as ph  # noqa: E402
from usep.core.ids import uuid7  # noqa: E402
from usep.ontology import load_ontology  # noqa: E402

TENANT, BUCKET = str(uuid7()), "demo"
PINS = ["app.app-reference@0.1.0", "org.org-reference@0.1.0", "project.project-reference@0.1.0"]


async def land(source: str, items: list[dict], s3) -> int:
    """What a connector hands the pipeline: each raw payload stored as an immutable snapshot, then a `raw.<source>` event that
    carries only a reference to it (snapshot first, event second). The payloads are the dummy ones; no source API is called."""
    writer = S3RawPayloadWriter(s3, BUCKET)
    publisher = S3RawEventPublisher(s3, BUCKET, TENANT, partitions=4)
    for i in items:
        ref = await writer.write(source, i["id"], i["raw"])
        await publisher.publish(RawEvent(
            source=source, source_type="dummy", source_ref=i["id"], source_url=f"https://dummy.invalid/{i['id']}", snapshot_ref=ref,
            checksum=payload_checksum(i["raw"]), retrieved_at=datetime.now(UTC), scope="demo",
            source_version="2026-01-01T00:00:00.000Z", acl=i.get("acl", {})))
    return len(items)


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

    # ---- stage 1: what the connectors hand over (stand-in output, landed by the S3 snapshot writer and raw event publisher)
    print("== C-01 connectors (stand-in output) ==")
    for source, items in data.items():
        n = asyncio.run(land(source, items, s3))
        print(f"  {source:<11} {n} documents -> raw snapshots + raw.{source} events")

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
