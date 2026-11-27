"""Ontology registry command line (C-06, C-07). Run from the repository root.

  keygen   --out key.pem --key-id dev-1                 development key; prints the trust-store entry (never for production)
  public-key --kms <arn>                                 trust-store entry for a KMS signing key
  publish  --signer kms:<arn>|file:<pem>:<key-id> (--local DIR | --bucket B [--prefix registry])
           [--root ontology] [--actor NAME]               run the checks, then publish the core and every pack as signed releases
  pin      --tenant T --packs a@1.0.0,b@1.0.0 (--local DIR | --bucket B) [--allow-reference] [--actor NAME]
  show     --tenant T (--local DIR | --bucket B)          current pins and the digest they give
  releases (--local DIR | --bucket B)                     every published version

`publish` refuses to run unless pack CI (check_ontology.py) and the golden-set check pass. There is no flag to skip them.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from usep.registry import Ed25519Signer, KmsSigner, Registry, RegistryError, TrustStore  # noqa: E402
from usep.registry.release import all_pack_ids, build_core_release, build_pack_release  # noqa: E402
from usep.registry.store import LocalRegistryStore, S3RegistryStore  # noqa: E402


def store(a):
    if a.local:
        return LocalRegistryStore(a.local)
    if not a.bucket:
        sys.exit("give --local DIR or --bucket B")
    import boto3
    return S3RegistryStore(boto3.client("s3"), a.bucket, a.prefix)


def registry(a):
    return Registry(store(a), TrustStore.load(a.trust), a.cache)


def signer(spec):
    kind, _, rest = spec.partition(":")
    if kind == "kms":
        import boto3
        return KmsSigner(boto3.client("kms"), rest)
    if kind == "file":
        path, _, key_id = rest.rpartition(":")
        return Ed25519Signer.from_pem_file(path, key_id)
    sys.exit("--signer must be kms:<arn> or file:<pem>:<key-id>")


def checks():
    for cmd in ([sys.executable, str(ROOT / "ontology/tools/check_ontology.py")], [sys.executable, str(ROOT / "evals/tools/check_golden.py")]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"refusing to publish: {Path(cmd[1]).name} failed\n{r.stdout}{r.stderr}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, need_store=True):
        if need_store:
            p.add_argument("--local"); p.add_argument("--bucket"); p.add_argument("--prefix", default="registry")
        p.add_argument("--trust", default=str(ROOT / "config/registry/trusted_keys.yaml"))
        p.add_argument("--cache")
        p.add_argument("--actor", default="cli")
    k = sub.add_parser("keygen"); k.add_argument("--out", required=True); k.add_argument("--key-id", required=True)
    pk = sub.add_parser("public-key"); pk.add_argument("--kms", required=True)
    pu = sub.add_parser("publish"); common(pu); pu.add_argument("--signer", required=True); pu.add_argument("--root", default=str(ROOT / "ontology"))
    pi = sub.add_parser("pin"); common(pi); pi.add_argument("--tenant", required=True); pi.add_argument("--packs", required=True); pi.add_argument("--allow-reference", action="store_true")
    pi.add_argument("--announce-bucket", help="publish an ontology.release event on the bus in this bucket")
    sh = sub.add_parser("show"); common(sh); sh.add_argument("--tenant", required=True)
    rl = sub.add_parser("releases"); common(rl)
    a = ap.parse_args()
    try:
        if a.cmd == "keygen":
            s = Ed25519Signer.generate(a.key_id)
            Path(a.out).write_bytes(s.private_pem())
            Path(a.out).chmod(0o600)
            print(f"- key_id: {a.key_id}\n  alg: ed25519\n  status: active\n  public_key_pem: |\n" + "".join(f"    {l}\n" for l in s.public_pem().splitlines()))
        elif a.cmd == "public-key":
            import boto3
            s = KmsSigner(boto3.client("kms"), a.kms)
            print(f"- key_id: {a.kms}\n  alg: ecdsa-p256-sha256\n  status: active\n  public_key_pem: |\n" + "".join(f"    {l}\n" for l in s.public_pem().splitlines()))
        elif a.cmd == "publish":
            checks()
            reg, sg = registry(a), signer(a.signer)
            for rel in (build_core_release(a.root), *[build_pack_release(a.root, p) for p in all_pack_ids(a.root)]):
                print(f"{rel.kind:5} {rel.id}@{rel.version}: {reg.publish(rel, sg, a.actor)}")
        elif a.cmd == "pin":
            announce = None
            if a.announce_bucket:
                import boto3
                from usep.adapters.s3.event_bus import S3EventBus
                from usep.ontology_runtime.events import publish_release, register_schemas
                from usep.ports.event_bus import SchemaRegistry
                sr = SchemaRegistry()
                register_schemas(sr)
                bus = S3EventBus(boto3.client("s3"), a.announce_bucket, sr)
                announce = lambda bundle, tenant: publish_release(bus, bundle, tenant)      # noqa: E731
            rec = registry(a).set_pins(a.tenant, [p.strip() for p in a.packs.split(",") if p.strip()], a.actor,
                                       allow_reference_only=a.allow_reference, on_release=announce)
            print(json.dumps(rec, indent=1))
        elif a.cmd == "show":
            print(json.dumps(registry(a).current_pins(a.tenant), indent=1))
        elif a.cmd == "releases":
            reg = registry(a)
            for kind, rid in sorted({(k.split("/")[1], k.split("/")[2]) for k in reg._store.list("releases") if k.endswith("manifest.json")}):
                print(f"{kind:5} {rid}: {', '.join(reg.versions(kind, rid))}")
    except RegistryError as exc:
        sys.exit(f"error: {exc}")


main()
