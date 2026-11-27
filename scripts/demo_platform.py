#!/usr/bin/env python3
"""One-command demo of what is built: ingestion, ontology checks, signed registry, fabric writer on real PostgreSQL.

    python scripts/demo_platform.py              # all four parts
    python scripts/demo_platform.py --only registry      # ingestion | ontology | registry | fabric
    python scripts/demo_platform.py --verbose    # print the full ingestion demo output

Needs the project virtual environment. If you start it with another Python it switches to `.venv/bin/python` by itself;
if there is no `.venv` it prints the setup command. Everything runs on dummy data in a temporary folder: no AWS, no network,
no secrets. The signing key is a throwaway development key. Exit code 1 if any expected outcome does not happen.
"""
import argparse
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"
NEEDED = ("yaml", "structlog", "psycopg", "cryptography", "pixeltable_pgserver", "boto3")
SETUP = ("python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt "
         "-r services/connectors/requirements.txt")


def _missing() -> list[str]:
    out = []
    for m in NEEDED:
        try:
            importlib.import_module(m)
        except ImportError:
            out.append(m)
    return out


def ensure_environment() -> None:
    miss = _missing()
    if not miss:
        return
    if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve() and not os.environ.get("USEP_DEMO_REEXEC"):
        os.environ["USEP_DEMO_REEXEC"] = "1"
        print(f"[demo] {sys.executable} lacks {', '.join(miss)}; switching to {VENV_PY}\n")
        os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])
    sys.exit(f"Missing Python packages: {', '.join(miss)}\nSet up the environment once, from the repo root:\n  {SETUP}")


class Failure(Exception):
    pass


def check(cond: bool, what: str) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {what}")
    if not cond:
        raise Failure(what)


def header(n: int, title: str) -> None:
    print(f"\n{'=' * 78}\n{n}. {title}\n{'=' * 78}")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)


# ---------------------------------------------------------------------------------------------------------------- 1
def part_ingestion(verbose: bool) -> None:
    header(1, "Ingestion: 7 sources -> connectors -> pipeline -> entities, edges, evidence, quarantine")
    r = run([sys.executable, str(ROOT / "scripts/demo_local.py"), "--show"])
    check(r.returncode == 0, "demo_local.py ran on 18 dummy records (in-memory S3, real pipeline code, stand-in connector output)")
    lines = r.stdout.splitlines()
    for ln in lines:
        if verbose or any(k in ln for k in ("handled", "quarantine reasons", "evidence objects", " edge ")):
            print("   ", ln.strip())
    check("handled 18 raw events | entities 12 | edges 1 | link edges 6 | evidence-only 2 | quarantined 4" in r.stdout,
          "12 entities, 1 edge, 6 cross-system link edges, 4 quarantined")
    check("{'Q-STATE': 2, 'Q-UNMAPPED': 2}" in r.stdout, "deliberate bad records quarantined with reason codes, content never logged")
    check("external model allowed 0 | blocked 14" in r.stdout, "unknown ACLs fail closed: no evidence may go to an external model")


# ---------------------------------------------------------------------------------------------------------------- 2
def part_ontology() -> None:
    header(2, "Ontology: pack CI (additive only, policies only tighten) and the golden set")
    r = run([sys.executable, "ontology/tools/check_ontology.py"])
    print("   ", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip())
    check(r.returncode == 0, "core, packs, templates, shapes and fixture pass")
    r = run([sys.executable, "evals/tools/check_golden.py"])
    print("   ", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip())
    check(r.returncode == 0 and "0 problems" in r.stdout, "golden set valid (synthetic draft: no scores to publish)")


# ---------------------------------------------------------------------------------------------------------------- 3
def part_registry(tmp: Path) -> None:
    header(3, "Registry (C-06/C-07): signed immutable releases, per-tenant pins, fail-closed loading")
    sys.path.insert(0, str(ROOT / "src"))
    import yaml
    from usep.registry import Ed25519Signer, Registry, RegistryError, TrustStore
    from usep.registry.release import all_pack_ids, build_core_release, build_pack_release
    from usep.registry.store import LocalRegistryStore

    reg_dir, key = tmp / "registry", tmp / "dev-key.pem"
    signer = Ed25519Signer.generate("demo-dev-1")
    key.write_bytes(signer.private_pem())
    trust_file = tmp / "trusted_keys.yaml"
    trust_file.write_text(yaml.safe_dump({"keys": [{"key_id": "demo-dev-1", "alg": "ed25519", "status": "active",
                                                    "public_key_pem": signer.public_pem()}]}))
    reg = Registry(LocalRegistryStore(reg_dir), TrustStore.load(trust_file), tmp / "cache")
    root = ROOT / "ontology"
    out = [reg.publish(build_core_release(root), signer, "demo")]
    for kind_id in all_pack_ids(root):
        out.append(reg.publish(build_pack_release(root, kind_id), signer, "demo"))
    check(out.count("published") == 7, f"published the core and 6 packs as signed releases ({out.count('published')} new)")
    check(reg.publish(build_core_release(root), signer, "demo") == "unchanged", "publishing identical content again is a no-op")

    rec = reg.set_pins("tenant-1", ["app.app-reference@0.1.0"], "demo", allow_reference_only=True)
    print(f"    pin #{rec['seq']} for tenant-1: core {rec['core_version']} + {rec['packs']}\n    digest {rec['ontology_digest'][:24]}...")
    b = reg.load_for_tenant("tenant-1", allow_reference_only=True)
    check(b.release.digest == rec["ontology_digest"], "services load the pinned, verified ontology; digest matches the pin")

    bundles = sorted(reg_dir.rglob("bundle.zip"))
    victim = next(p for p in bundles if "app-reference" in str(p) and "retail" not in str(p))
    original = victim.read_bytes()
    victim.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    try:
        Registry(LocalRegistryStore(reg_dir), TrustStore.load(trust_file), tmp / "cache2").load_for_tenant(
            "tenant-1", allow_reference_only=True)
        check(False, "a tampered bundle must not load")
    except RegistryError:
        check(True, "one flipped byte in a stored bundle: load refused (fail closed)")
    victim.write_bytes(original)

    empty = tmp / "no_trust.yaml"
    empty.write_text("keys: []\n")
    try:
        Registry(LocalRegistryStore(reg_dir), TrustStore.load(empty), tmp / "cache3").load_for_tenant(
            "tenant-1", allow_reference_only=True)
        check(False, "an untrusted signer must not load")
    except RegistryError:
        check(True, "no trusted key: nothing signed loads, even though the content is intact")


# ---------------------------------------------------------------------------------------------------------------- 4
def part_fabric(tmp: Path) -> None:
    header(4, "Fabric writer (C-04) on real PostgreSQL 16: atomic commit, idempotency, ordering, outbox")
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
    import pixeltable_pgserver
    import psycopg
    from tests.fabric.helpers import edge, node, ref, retraction
    from usep.adapters.postgres import PostgresFabricStore, migrate
    from usep.fabric import FabricWriter, OutboxRelay

    server = pixeltable_pgserver.get_server(tmp / "pg")
    try:
        dsn = server.get_uri()
        with psycopg.connect(dsn) as c:
            applied = migrate(c)
        check(applied == ["0001_fabric.sql"], "schema migrated (row-level security on every tenant table)")
        store = PostgresFabricStore(dsn)
        w = FabricWriter(store)

        def step(label: str, got: str, want: str) -> None:
            print(f"    {label:<58} -> {got}")
            check(got == want, f"{label}: {want}")

        step("node ABC-1", w.handle(node(sid="ABC-1")).status, "committed")
        step("same event delivered again", w.handle(node(sid="ABC-1")).status, "duplicate")
        step("edge ABC-1 -> ABC-2 (ABC-2 not seen yet)", w.handle(edge(ref("ABC-1"), ref("ABC-2"))).status, "pending")
        step("node ABC-2 arrives (pending edge gets linked)", w.handle(node(sid="ABC-2")).status, "committed")
        step("older version of ABC-1 (out of order)", w.handle(node(sid="ABC-1", valid_from="2025-01-01T00:00:00Z",
                                                                    version="0")).status, "stale")
        step("ABC-1 arrives as a Service (it is an Issue)", w.handle(node(sid="ABC-1", type="Service",
                                                                          valid_from="2026-06-01T00:00:00Z", version="9")).status,
             "rejected")
        r = w.handle(retraction("ABC-2"))
        print(f"    source deletes ABC-2 -> retracted {r.extra}")
        check(r.extra == {"entities": 1, "edges": 1}, "retraction marks the entity and its edge; history stays")

        with psycopg.connect(dsn) as c:
            hist = c.execute("SELECT subject_kind, applied, reason FROM fabric_assertion ORDER BY recorded_at").fetchall()
        check(len(hist) == 5 and (("node", False, "stale") in hist), f"append-only history kept {len(hist)} assertions, incl. the stale one")
        with psycopg.connect(dsn) as c:
            rej = c.execute("SELECT code FROM fabric_rejected").fetchall()
        check(rej == [("type_conflict",)], "the type conflict is parked in fabric_rejected, not lost and not fatal")

        st = store.outbox_status()
        print(f"    outbox before relay: {st.pending} pending")
        got: list[str] = []

        class Bus:
            def publish(self, topic, key, type, tenant_id, payload, headers=None):
                got.append(f"{topic} {type}")
                print(f"      bus <- {topic:<13} {type}")

        res = OutboxRelay(store, Bus()).drain()
        check(res.published == st.pending and store.outbox_status().pending == 0, "relay published every committed change, in order, once")
        check("commit.edge edge.retracted" in got and "commit.entity entity.retracted" in got, "retractions reach projectors too")
    finally:
        server.cleanup()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=("ingestion", "ontology", "registry", "fabric"))
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    ensure_environment()
    tmp = Path(tempfile.mkdtemp(prefix="usep-demo-"))
    ok = True
    try:
        for name, fn in (("ingestion", lambda: part_ingestion(a.verbose)), ("ontology", part_ontology),
                         ("registry", lambda: part_registry(tmp)), ("fabric", lambda: part_fabric(tmp))):
            if a.only in (None, name):
                try:
                    fn()
                except Failure as exc:
                    ok = False
                    print(f"\n  >> part '{name}' stopped: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("All demo checks passed." if ok else "Some demo checks FAILED."))
    print("Not shown (not built): entity resolver, graph and vector projectors. Registry key is a throwaway; IaC and CI never run.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
