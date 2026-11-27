"""Registry client (read side): what every service uses. It holds no signing rights and needs only read access to S3.

`load(pins)`: for each pinned pack and the core release it chooses, fetch the manifest and bundle, verify the signature
against the trust store, check the bundle against the signed body, unpack into a local cache laid out like the ontology folder,
and run the one loader over it. The loader's digest of that tree equals the digest of the same files in Git. Anything wrong
(unsigned, altered, revoked key, missing, unpinned, reference-only where not allowed) raises RegistryError or OntologyLoadError,
and the caller keeps the ontology it already has.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from usep.ontology_runtime.loader import PackPin, load_ontology, satisfies
from usep.ontology_runtime.model import OntologyBundle
from usep.registry.errors import RegistryError
from usep.registry.release import canonical, check_body_against_bundle, sha256
from usep.registry.signing import TrustStore

RELEASES = "releases"
PINS = "pins"


def _ver(v: str) -> tuple[int, int, int]:
    a, b, c = v.split(".")
    return int(a), int(b), int(c)


class RegistryClient:
    def __init__(self, store: Any, trust: TrustStore, cache_dir: str | Path | None = None) -> None:
        self._store, self._trust = store, trust
        self._cache = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "usep-ontology-cache"

    # ---------------------------------------------------------------- releases
    def versions(self, kind: str, rid: str) -> list[str]:
        seen = {k.split("/")[3] for k in self._store.list(f"{RELEASES}/{kind}/{rid}") if k.endswith("/manifest.json")}
        return sorted(seen, key=_ver)

    def get_release(self, kind: str, rid: str, version: str, now: datetime | None = None) -> tuple[dict[str, Any], dict[str, bytes], str]:
        """(signed body, files, key id of the signer), verified. Raises RegistryError."""
        base = f"{RELEASES}/{kind}/{rid}/{version}"
        raw = self._store.get(f"{base}/manifest.json")
        if raw is None:
            raise RegistryError(f"{rid}@{version} is not published")
        env = json.loads(raw)
        body = env["body"]
        if (body.get("kind"), body.get("id"), body.get("version")) != (kind, rid, version):
            raise RegistryError(f"{rid}@{version}: manifest is for a different release")
        key_id = self._trust.verify(canonical(body), env["signature"], now)
        bundle = self._store.get(f"{base}/bundle.zip")
        if bundle is None:
            raise RegistryError(f"{rid}@{version}: bundle is missing")
        return body, check_body_against_bundle(body, bundle), key_id

    def choose_core(self, pack_bodies: list[dict[str, Any]], now: datetime | None = None) -> str:
        """The highest published core version that every pinned pack accepts."""
        for v in reversed(self.versions("core", "core")):
            if all(satisfies(v, b.get("requires_core")) for b in pack_bodies):
                return v
        raise RegistryError("no published core release satisfies every pinned pack")

    # ---------------------------------------------------------------- load
    def load(self, pins: list[str], *, allow_reference_only: bool = False, now: datetime | None = None) -> OntologyBundle:
        parsed = [PackPin.parse(p) for p in pins]
        packs = [self.get_release("pack", p.id, p.version, now) for p in parsed]
        for body, _, _ in packs:
            if body.get("reference_only") and not allow_reference_only:
                raise RegistryError(f"{body['id']} is reference-only (placeholder content) and this registry client does not allow it")
        core_v = self.choose_core([b for b, _, _ in packs], now)
        core = self.get_release("core", "core", core_v, now)
        releases = [core, *packs]
        root = self._materialize(releases)
        return load_ontology(root, parsed, allow_reference_only=allow_reference_only, allow_unsigned=False,
                             signed_ids=["core", *[p.id for p in parsed]])

    def _materialize(self, releases: list[tuple[dict[str, Any], dict[str, bytes], str]]) -> Path:
        key = sha256("|".join(sorted(f"{b['kind']}:{b['id']}@{b['version']}:{b['digest']}" for b, _, _ in releases)).encode())[:32]
        target = self._cache / key / "ontology"
        expected = {path: data for _, files, _ in releases for path, data in files.items()}
        if target.is_dir() and self._tree_matches(target, expected):
            return target
        shutil.rmtree(self._cache / key, ignore_errors=True)               # a stale or altered cache is rebuilt, never trusted
        tmp = Path(tempfile.mkdtemp(prefix="build-", dir=self._ensure_cache()))
        for path, data in expected.items():
            p = tmp / "ontology" / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self._cache / key).parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp.rename(self._cache / key)
        except OSError:                                                    # another process won the race: use theirs if intact
            shutil.rmtree(tmp, ignore_errors=True)
            if not self._tree_matches(target, expected):
                raise RegistryError("ontology cache could not be written") from None
        return target

    def _ensure_cache(self) -> Path:
        self._cache.mkdir(parents=True, exist_ok=True)
        return self._cache

    @staticmethod
    def _tree_matches(root: Path, expected: dict[str, bytes]) -> bool:
        on_disk = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
        return set(on_disk) == set(expected) and all(on_disk[k].read_bytes() == v for k, v in expected.items())

    # ---------------------------------------------------------------- pins
    def current_pins(self, tenant_id: str) -> dict[str, Any] | None:
        keys = [k for k in self._store.list(f"{PINS}/{tenant_id}") if k.endswith(".json")]
        if not keys:
            return None
        rec = json.loads(self._store.get(keys[-1]))
        if rec.get("tenant_id") != tenant_id:
            raise RegistryError("pin record belongs to another tenant")
        return rec

    def load_for_tenant(self, tenant_id: str, *, allow_reference_only: bool = False) -> OntologyBundle:
        rec = self.current_pins(tenant_id)
        if rec is None:
            raise RegistryError(f"tenant {tenant_id} has no pinned ontology")
        return self.load(list(rec["packs"]), allow_reference_only=allow_reference_only)
