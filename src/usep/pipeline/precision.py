"""Edge precision check: sample edge candidates per relationship type, collect human labels, report precision.

The design notes ask for about 100 labelled edges per relation type before an inferred edge is trusted. This module
draws a repeatable stratified sample (relation, method) from `entity.edge_candidate` events and scores a labelled
sheet. Nothing here changes the graph. A label is `y` (correct), `n` (wrong) or blank (not yet reviewed, left out).
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

COLUMNS = ["idempotency_key", "relation", "method", "rule", "confidence", "from", "to", "evidence_ref", "label"]


def edge_rows(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per distinct edge candidate (replays share an idempotency key)."""
    seen: dict[str, dict[str, Any]] = {}
    for ev in events:
        p = ev.get("payload") or {}
        if p.get("kind") != "edge":
            continue
        key = p.get("idempotency_key") or (ev.get("headers") or {}).get("idempotency_key") or ""
        a, b, prov = p.get("from") or {}, p.get("to") or {}, p.get("provenance") or {}
        seen[key] = {"idempotency_key": key, "relation": p.get("type"), "method": prov.get("method", "rule"),
                     "rule": prov.get("rule", ""), "confidence": (p.get("attributes") or {}).get("confidence", 1.0),
                     "from": f"{a.get('source_system')}:{a.get('source_id')}",
                     "to": f"{b.get('source_system')}:{b.get('source_id') or b.get('repository_ref')}",
                     "evidence_ref": p.get("evidence_ref", ""), "label": ""}
    return list(seen.values())


def sample(rows: list[dict[str, Any]], per_relation: int = 100, seed: str = "usep") -> list[dict[str, Any]]:
    """At most `per_relation` rows per relation, split evenly across methods, in a repeatable order (hash of seed and key)."""
    by_rel: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_rel[r["relation"]][r["method"]].append(r)
    order = lambda r: hashlib.sha256(f"{seed}|{r['idempotency_key']}".encode()).hexdigest()   # noqa: E731
    out: list[dict[str, Any]] = []
    for rel in sorted(by_rel):
        pools = {m: sorted(v, key=order) for m, v in sorted(by_rel[rel].items())}
        picked: list[dict[str, Any]] = []
        while len(picked) < per_relation and any(pools.values()):
            for m in list(pools):                       # round robin keeps a rare method from being crowded out
                if pools[m] and len(picked) < per_relation:
                    picked.append(pools[m].pop(0))
        out += picked
    return out


def write_sheet(rows: Iterable[Mapping[str, Any]], path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def score(path: str | Path) -> dict[str, dict[str, Any]]:
    """Precision per relation and per (relation, method), from the reviewed rows only."""
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])          # key -> [correct, reviewed]
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lab = (r.get("label") or "").strip().lower()
            if lab not in ("y", "n"):
                continue
            for k in (r["relation"], f"{r['relation']}/{r['method']}"):
                tally[k][1] += 1
                tally[k][0] += lab == "y"
    return {k: {"reviewed": n, "correct": c, "precision": round(c / n, 3)} for k, (c, n) in sorted(tally.items())}


def load_events(root: str | Path) -> list[dict[str, Any]]:
    """Read bus objects from a local copy of the bucket (for example `aws s3 sync s3://<bucket>/bus ./bus`)."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(root).rglob("*.json"))
            if "entity." in p.as_posix() and "_offsets" not in p.as_posix()]
