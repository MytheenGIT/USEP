"""Ontology releases on the event bus. HLD 4.4 (interfaces): events include ontology releases.

A release event carries the versions in force and a digest, not the definitions. Consumers (pipeline workers, the
resolver, model workers) reload from the registry checkout and must arrive at the same digest, or they keep what they
have and report the mismatch. This is the 'distribute configuration, not source records' arrow in the data-flow figure.
"""
from __future__ import annotations

from typing import Callable

from usep.core.errors import OntologyLoadError
from usep.ontology.model import OntologyBundle
from usep.ports.event_bus import Event, EventBus, SchemaRegistry, consume

TOPIC = "ontology.release"
EVENT_TYPE = "ontology.released"


def register_schemas(registry: SchemaRegistry) -> None:
    registry.register(TOPIC, 1, ("core_version", "packs", "digest"))


def publish_release(bus: EventBus, bundle: OntologyBundle, tenant_id: str) -> Event:
    """Key by tenant so one tenant's releases are ordered. Packs are pinned per tenant, the core is shared."""
    return bus.publish(TOPIC, tenant_id, EVENT_TYPE, tenant_id, bundle.release.as_dict())


class OntologyConfigCache:
    """A consumer's cached ontology. It changes only to a bundle whose digest matches the release event.

    `load` receives the pins from the event (a list of 'pack-id@version') and returns an OntologyBundle.
    Runs that started under the old bundle keep their reference to it (a run finishes under its start version).
    """

    def __init__(self, tenant_id: str, group: str, load: Callable[[list[str]], OntologyBundle],
                 initial: OntologyBundle | None = None) -> None:
        self.tenant_id, self.group, self._load = tenant_id, group, load
        self.current = initial
        self.last_error: str | None = None

    def refresh(self, bus: EventBus) -> bool:
        changed = False

        def handle(event: Event) -> None:
            nonlocal changed
            if event.tenant_id != self.tenant_id:
                return
            if self.current and event.payload["digest"] == self.current.release.digest:
                return
            pins = [f"{p['id']}@{p['version']}" for p in event.payload["packs"] if p["id"] != "core"]
            try:
                bundle = self._load(pins)
            except OntologyLoadError as exc:
                self.last_error = f"release {event.payload['digest'][:12]} refused: {exc}"
                return                                              # fail closed: keep the cached ontology
            if bundle.release.digest != event.payload["digest"]:
                self.last_error = f"release {event.payload['digest'][:12]}: local digest differs, keeping current"
                return
            self.current, self.last_error, changed = bundle, None, True

        consume(bus, TOPIC, self.group, handle)
        return changed
