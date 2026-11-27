"""Registry (write side): publish signed releases and move a tenant's pins. Needs signing and write rights; services do not.

Publishing is idempotent for identical content and refuses a version that already exists with different content: a version
number is a promise. Pins are an append-only history, one record per change, and can point only at a set of releases that
verifies, fits one core, and loads cleanly. A reference-only pack can be pinned only where the caller says placeholder
content is acceptable (a development stack).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from usep.ontology.model import OntologyBundle
from usep.registry.client import PINS, RELEASES, RegistryClient
from usep.registry.errors import RegistryError
from usep.registry.release import Release, canonical
from usep.registry.signing import Signer, sign_body


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Registry(RegistryClient):
    def publish(self, release: Release, signer: Signer, actor: str) -> str:
        """Returns 'published' or 'unchanged'. Raises RegistryError if the version exists with different content."""
        base = f"{RELEASES}/{release.kind}/{release.id}/{release.version}"
        existing = self._store.get(f"{base}/manifest.json")
        if existing is not None:
            if json.loads(existing)["body"] == release.body:
                return "unchanged"
            raise RegistryError(f"{release.id}@{release.version} is already published with different content; bump the version")
        if not self._store.put_if_absent(f"{base}/bundle.zip", release.bundle) and self._store.get(f"{base}/bundle.zip") != release.bundle:
            raise RegistryError(f"{release.id}@{release.version}: a different bundle is already stored")
        signature = sign_body(signer, canonical(release.body))
        self._trust.verify(canonical(release.body), signature)       # a release nobody trusts must not be published
        env = {"body": release.body, "signature": signature, "published_at": _now(), "published_by": actor}
        if not self._store.put_if_absent(f"{base}/manifest.json", json.dumps(env, sort_keys=True).encode()):
            raise RegistryError(f"{release.id}@{release.version}: published concurrently; retry")
        return "published"

    def set_pins(self, tenant_id: str, packs: list[str], actor: str, *, allow_reference_only: bool = False,
                 on_release: Callable[[OntologyBundle, str], Any] | None = None) -> dict[str, Any]:
        """Pin a tenant to these packs (and the core they need). Proves the set loads before recording it."""
        bundle = self.load(packs, allow_reference_only=allow_reference_only)          # raises if anything is wrong
        for attempt in range(3):
            cur = self.current_pins(tenant_id)
            seq = (int(cur["seq"]) if cur else 0) + 1
            rec = {"tenant_id": tenant_id, "seq": seq, "core_version": bundle.release.core_version, "packs": list(packs),
                   "ontology_digest": bundle.release.digest, "actor": actor, "at": _now(),
                   "previous_digest": cur["ontology_digest"] if cur else None}
            if self._store.put_if_absent(f"{PINS}/{tenant_id}/{seq:010d}.json", json.dumps(rec, sort_keys=True).encode()):
                if on_release is not None:
                    on_release(bundle, tenant_id)                                         # announce ontology.release
                return rec
        raise RegistryError("pins changed concurrently; retry")
