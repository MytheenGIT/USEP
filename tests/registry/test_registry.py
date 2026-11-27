"""Ontology registry (C-06) and signing (C-07): publish, verify, pin, load, and every way it must refuse."""
import base64
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tests.fake_s3 import FakeS3
from usep.core.errors import OntologyLoadError
from usep.ontology_runtime import load_ontology, resolve_pins
from usep.registry import Ed25519Signer, KmsSigner, Registry, RegistryClient, RegistryError, TrustStore
from usep.registry.release import all_pack_ids, build_core_release, build_pack_release, canonical
from usep.registry.signing import ECDSA, TrustedKey, sign_body
from usep.registry.store import LocalRegistryStore, S3RegistryStore

ROOT = Path(__file__).resolve().parents[2] / "ontology"
PACKS = ["app.app-reference", "org.org-reference", "project.project-reference"]
PINS = [f"{p}@0.1.0" for p in PACKS]
T = "00000000-0000-7000-8000-000000000001"


def trust_for(signer, **kw):
    return TrustStore([TrustedKey(signer.key_id, signer.alg, signer.public_pem(), **kw)])


def publish_all(reg, signer, root=ROOT):
    for rel in (build_core_release(root), *[build_pack_release(root, p) for p in all_pack_ids(root)]):
        reg.publish(rel, signer, "test")


@pytest.fixture()
def signer():
    return Ed25519Signer.generate("test-key-1")


@pytest.fixture()
def reg(tmp_path, signer):
    r = Registry(LocalRegistryStore(tmp_path / "store"), trust_for(signer), tmp_path / "cache")
    publish_all(r, signer)
    return r


def test_registry_load_equals_the_git_load_and_every_pack_is_marked_signed(reg):
    b = reg.load(PINS, allow_reference_only=True)
    git = load_ontology(ROOT, resolve_pins(ROOT, PACKS), allow_reference_only=True)
    assert b.release.digest == git.release.digest                       # same files, same digest
    assert set(b.templates) == set(git.templates) and set(b.concepts) == set(git.concepts)
    assert all(p.signed for p in b.release.packs)
    assert not any(p.signed for p in git.release.packs)                 # a Git checkout is never signed


def test_a_git_checkout_is_refused_when_unsigned_packs_are_not_allowed():
    with pytest.raises(OntologyLoadError, match="unsigned"):
        load_ontology(ROOT, resolve_pins(ROOT, PACKS), allow_reference_only=True, allow_unsigned=False)


def test_reference_only_packs_are_refused_unless_allowed(reg):
    with pytest.raises(RegistryError, match="reference-only"):
        reg.load(PINS)
    with pytest.raises(RegistryError, match="reference-only"):
        reg.set_pins(T, PINS, "me")


def test_publish_is_idempotent_and_a_version_cannot_change(tmp_path, signer, reg):
    assert reg.publish(build_core_release(ROOT), signer, "x") == "unchanged"
    edited = tmp_path / "ontology"
    shutil.copytree(ROOT, edited)
    f = edited / "core/vocabularies.yml"
    f.write_text(f.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="different content"):
        reg.publish(build_core_release(edited), signer, "x")


def test_an_untrusted_signer_cannot_publish(tmp_path, signer):
    other = Ed25519Signer.generate("someone-else")
    r = Registry(LocalRegistryStore(tmp_path / "s"), trust_for(signer))
    with pytest.raises(RegistryError, match="trusted"):
        r.publish(build_core_release(ROOT), other, "x")


def path_of(reg, kind, rid, ver, name):
    return reg._store._root / f"releases/{kind}/{rid}/{ver}/{name}"


def test_altered_bundle_is_refused(reg):
    p = path_of(reg, "pack", "app.app-reference", "0.1.0", "bundle.zip")
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(RegistryError, match="does not match its manifest"):
        reg.load(PINS, allow_reference_only=True)


def test_altered_manifest_fails_the_signature(reg):
    p = path_of(reg, "pack", "app.app-reference", "0.1.0", "manifest.json")
    env = json.loads(p.read_text())
    env["body"]["requires_core"] = ">=0.0.1"
    p.write_text(json.dumps(env))
    with pytest.raises(RegistryError, match="signature"):
        reg.load(PINS, allow_reference_only=True)


def test_a_manifest_copied_from_another_release_is_refused(reg):
    a = path_of(reg, "pack", "app.app-reference", "0.1.0", "manifest.json")
    o = path_of(reg, "pack", "org.org-reference", "0.1.0", "manifest.json")
    a.write_bytes(o.read_bytes())
    with pytest.raises(RegistryError, match="different release"):
        reg.load(PINS, allow_reference_only=True)


def test_revoked_and_expired_keys_and_unknown_keys_are_refused(reg, signer):
    for kw in ({"status": "revoked"}, {"not_after": "2020-01-01T00:00:00Z"}):
        c = RegistryClient(reg._store, trust_for(signer, **kw))
        with pytest.raises(RegistryError, match="signature"):
            c.load(PINS, allow_reference_only=True)
    with pytest.raises(RegistryError, match="signature"):
        RegistryClient(reg._store, TrustStore([])).load(PINS, allow_reference_only=True)
    assert RegistryClient(reg._store, trust_for(signer)).load(PINS, allow_reference_only=True)      # the good key still works


def test_unpublished_pack_and_unsatisfied_core_are_refused(tmp_path, signer):
    r = Registry(LocalRegistryStore(tmp_path / "s"), trust_for(signer), tmp_path / "c")
    r.publish(build_core_release(ROOT), signer, "x")
    with pytest.raises(RegistryError, match="not published"):
        r.load(["app.app-reference@0.1.0"], allow_reference_only=True)
    edited = tmp_path / "ontology"
    shutil.copytree(ROOT, edited)
    pm = edited / "packs/app/app-reference/pack.yml"
    pm.write_text(pm.read_text(encoding="utf-8").replace('">=0.1.0 <1.0.0"', '">=0.2.0 <1.0.0"'), encoding="utf-8")
    r.publish(build_pack_release(edited, "app.app-reference"), signer, "x")
    with pytest.raises(RegistryError, match="no published core"):
        r.load(["app.app-reference@0.1.0"], allow_reference_only=True)


def test_a_bundle_with_an_unsafe_path_is_refused(tmp_path, signer):
    from usep.registry.release import Release, content_digest, sha256
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.yml", "x: 1")
    bundle = buf.getvalue()
    files = {"../evil.yml": sha256(b"x: 1")}
    body = {"schema": 1, "kind": "pack", "id": "app.evil", "version": "0.1.0", "requires_core": ">=0.1.0 <1.0.0", "level": "application",
            "reference_only": False, "files": files, "digest": content_digest(files), "bundle_sha256": sha256(bundle)}
    r = Registry(LocalRegistryStore(tmp_path / "s"), trust_for(signer), tmp_path / "c")
    r.publish(Release(body, bundle), signer, "x")
    with pytest.raises(RegistryError, match="unsafe path"):
        r.get_release("pack", "app.evil", "0.1.0")


def test_pins_are_an_append_only_history_and_announce_a_release(reg):
    seen = []
    a = reg.set_pins(T, PINS, "alice", allow_reference_only=True, on_release=lambda b, t: seen.append((t, b.release.digest)))
    b = reg.set_pins(T, PINS[:2], "bob", allow_reference_only=True)
    assert (a["seq"], b["seq"]) == (1, 2) and b["previous_digest"] == a["ontology_digest"] and a["ontology_digest"] != b["ontology_digest"]
    assert seen == [(T, a["ontology_digest"])]
    assert reg.current_pins(T)["actor"] == "bob" and reg.current_pins("00000000-0000-7000-8000-000000000002") is None
    assert len(reg._store.list(f"pins/{T}")) == 2                       # nothing was overwritten
    assert reg.load_for_tenant(T, allow_reference_only=True).release.digest == b["ontology_digest"]


def test_a_pin_record_for_another_tenant_is_refused(reg):
    reg.set_pins(T, PINS, "a", allow_reference_only=True)
    other = "00000000-0000-7000-8000-000000000002"
    shutil.copytree(reg._store._root / "pins" / T, reg._store._root / "pins" / other)
    with pytest.raises(RegistryError, match="another tenant"):
        reg.current_pins(other)


def test_a_pin_that_does_not_load_is_not_recorded(reg):
    with pytest.raises(RegistryError, match="not published"):
        reg.set_pins(T, ["app.app-reference@9.9.9"], "a", allow_reference_only=True)
    assert reg.current_pins(T) is None


def test_an_altered_cache_is_rebuilt_not_trusted(reg):
    b = reg.load(PINS, allow_reference_only=True)
    cached = next(reg._cache.glob("*/ontology/core/vocabularies.yml"))
    cached.write_text("tampered: true\n", encoding="utf-8")
    again = reg.load(PINS, allow_reference_only=True)
    assert again.release.digest == b.release.digest and "tampered" not in cached.read_text(encoding="utf-8")


def test_s3_store_works_like_the_local_one(signer, tmp_path):
    s3 = FakeS3()
    r = Registry(S3RegistryStore(s3, "bkt", "registry"), trust_for(signer), tmp_path / "c")
    publish_all(r, signer)
    assert r.versions("core", "core") == ["0.1.0"]
    rec = r.set_pins(T, PINS, "a", allow_reference_only=True)
    assert rec["seq"] == 1 and any(k.startswith("registry/pins/") for k in s3.objects)
    assert r.load_for_tenant(T, allow_reference_only=True).release.digest == rec["ontology_digest"]
    assert r.publish(build_core_release(ROOT), signer, "x") == "unchanged"


class FakeKms:
    """What boto3's kms client does for an ECC_NIST_P256 SIGN_VERIFY key, with a local key."""
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, KeyId, Message, MessageType, SigningAlgorithm):
        assert (MessageType, SigningAlgorithm) == ("RAW", "ECDSA_SHA_256")
        return {"Signature": self.key.sign(Message, ec.ECDSA(hashes.SHA256()))}

    def get_public_key(self, KeyId):
        return {"PublicKey": self.key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)}


def test_kms_signer_signatures_verify_against_the_trust_store(tmp_path):
    s = KmsSigner(FakeKms(), "arn:aws:kms:eu-west-1:1:key/abc")
    r = Registry(LocalRegistryStore(tmp_path / "s"), trust_for(s), tmp_path / "c")
    publish_all(r, s)
    assert r.load(PINS, allow_reference_only=True).release.packs[0].signed
    sig = sign_body(s, b"data")
    assert sig["alg"] == ECDSA
    with pytest.raises(RegistryError):
        trust_for(s).verify(b"other data", sig)


def test_trust_store_file_validation(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("keys:\n  - {key_id: k, alg: rsa, public_key_pem: x}\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="unsupported"):
        TrustStore.load(f)
    shipped = Path(__file__).resolve().parents[2] / "config/registry/trusted_keys.yaml"
    with pytest.raises(RegistryError):
        TrustStore.load(shipped).verify(b"x", {"alg": "ed25519", "key_id": "k", "sig": base64.b64encode(b"x").decode()})   # empty: nothing loads


def test_command_line_end_to_end(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    key, store, trust = tmp_path / "k.pem", tmp_path / "store", tmp_path / "trust.yaml"
    run = lambda *a: subprocess.run([sys.executable, str(repo / "scripts/registry.py"), *a], capture_output=True, text=True, cwd=repo)  # noqa: E731
    out = run("keygen", "--out", str(key), "--key-id", "ci-1")
    assert out.returncode == 0, out.stderr
    trust.write_text("keys:\n" + "".join("  " + l + "\n" for l in out.stdout.strip().splitlines()), encoding="utf-8")
    pub = run("publish", "--signer", f"file:{key}:ci-1", "--local", str(store), "--trust", str(trust), "--cache", str(tmp_path / "c"))
    assert pub.returncode == 0 and "core  core@0.1.0: published" in pub.stdout, pub.stdout + pub.stderr
    again = run("publish", "--signer", f"file:{key}:ci-1", "--local", str(store), "--trust", str(trust), "--cache", str(tmp_path / "c"))
    assert "unchanged" in again.stdout and "published" not in again.stdout.replace("unchanged", "")
    refused = run("pin", "--tenant", T, "--packs", ",".join(PINS), "--local", str(store), "--trust", str(trust), "--cache", str(tmp_path / "c"))
    assert refused.returncode != 0 and "reference-only" in refused.stderr
    pin = run("pin", "--tenant", T, "--packs", ",".join(PINS), "--local", str(store), "--trust", str(trust), "--cache", str(tmp_path / "c"), "--allow-reference")
    assert pin.returncode == 0 and json.loads(pin.stdout)["seq"] == 1, pin.stderr
    assert json.loads(run("show", "--tenant", T, "--local", str(store), "--trust", str(trust)).stdout)["packs"] == PINS
