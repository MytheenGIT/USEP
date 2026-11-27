"""Runs a configuration: one sync per connector the admin selected, with what they entered or the server's credentials.

A run goes through the same ingestion path as a scheduled one (rate limit and retry, the raw payload writer into the
raw store, the audit trail), but its cursors start empty so the whole configuration is read and the graph is complete.
A source that cannot run is reported with a reason; it never fails the others. No source is mandatory: only the ones
selected are read, and the configuration is ready when every selected one was read. Typed credentials are held in
memory only and dropped when the run ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from common.client_base import ClientRuntime
from common.json_file_sink import JsonFileSink
from common.source_document import SourceDocument
from common.sync_models import SyncStatus
from config import Settings
from console_api.connectors import build_connector
from console_api.graph import build_graph
from console_api.errors import ConsoleError
from console_api.models import Configuration, ConnectorSummary, SourceStatus
from console_api.ontology import apply_ontology
from console_api.secrets_store import Credentials, SecretStore
from console_api.store import ConfigurationStore
from console_api.validation import SPECS, server_base_url, server_credentials
from sync_service import SyncService
from usep.ingestion.ports.audit import AuditEvent, AuditPort

logger = structlog.get_logger(__name__)


@dataclass
class _Plan:
    key: str  # connector key: jira, confluence, gitlab or figma (also the source name)
    connector: object | None = None
    client: object | None = None
    skip_reason: str | None = None


def _short(message: str) -> str:
    return " ".join(message.split())[:300]


class ConfigProcessor:
    def __init__(
        self,
        settings: Settings,
        store: ConfigurationStore,
        audit: AuditPort,
        secrets: SecretStore,
        pipeline: Callable[..., SyncService],
        runtime_for: Callable[[str, str], ClientRuntime | None] | None = None,
    ) -> None:
        self._s = settings
        self._store = store
        self._audit = audit
        self._secrets = secrets
        self._pipeline = pipeline  # container.new_sync_service
        self._runtime_for = runtime_for

    def _credentials(self, config: Configuration, key: str) -> Credentials | None:
        mode = config.connectors[key].credentials
        if mode == "server":
            return server_credentials(self._s, key)
        if mode == "provided":
            return self._secrets.get(config.id, key)
        return None

    def _plan(self, config: Configuration) -> list[_Plan]:
        plans: list[_Plan] = []
        for key, summary in config.connectors.items():
            if not summary.enabled:
                continue  # not selected: nothing to read, nothing to report
            creds = self._credentials(config, key)
            if creds is None:
                plans.append(_Plan(key, skip_reason="Credentials are not available to the server. Submit the configuration again."))
                continue
            base = summary.base_url or server_base_url(self._s, key)
            connector, client = build_connector(
                key, base_url=base, creds=creds, targets=summary.targets, jql_queries=summary.jql_queries,
                all_member_projects=summary.all_member_projects, settings=self._s,
                auth_method=summary.auth_method, encoded_query=summary.encoded_query,
                runtime=self._runtime_for(key, base) if self._runtime_for else None,
            )
            plans.append(_Plan(key, connector, client))
        return plans

    async def _read(self, config: Configuration, plans: list[_Plan]) -> tuple[list[SourceStatus], dict[str, list[SourceDocument]]]:
        """Read the planned sources. Returns a status for each, and the documents of the ones that succeeded."""
        runnable = [p for p in plans if p.connector is not None]
        extra: dict[str, dict[str, Any]] = {
            p.key: {"configuration_id": config.id, "connector": config.connectors[p.key].model_dump()} for p in runnable
        }
        service = self._pipeline(
            {p.key: p.connector for p in runnable},
            json_sink=JsonFileSink(str(self._store.directory(config.id) / "runs")) if self._s.json_sink_enabled else None,
            snapshot_extra=extra,
        )
        try:
            # GitLab: every repository the token's user is a member of. "Could not look" is a failure, and so is
            # "nothing to read": neither may pass as a successful, empty run.
            lookup_failed = await service.refresh_scopes()
            blocked: dict[str, str] = {p.key: f"Could not list what to read: {lookup_failed[p.key]}" for p in runnable if p.key in lookup_failed}
            blocked |= {p.key: "Nothing to read: no repositories were found for this token" for p in runnable if p.key not in blocked and not p.connector.scopes}  # type: ignore[union-attr]
            to_run = [p for p in runnable if p.key not in blocked]
            results = await asyncio.gather(*(service.sync_source(p.key) for p in to_run))
        finally:
            for p in runnable:
                await p.client.aclose()  # type: ignore[union-attr]

        by_source = {r.source.value: r for r in results}
        statuses: list[SourceStatus] = []
        documents: dict[str, list[SourceDocument]] = {}
        for plan in plans:
            if plan.connector is None:
                statuses.append(SourceStatus(source=plan.key, state="skipped", detail=plan.skip_reason))
            elif plan.key in blocked:
                statuses.append(SourceStatus(source=plan.key, state="failed", detail=_short(blocked[plan.key])))
            else:
                result = by_source[plan.key]
                if result.status == SyncStatus.SUCCESS:
                    documents[plan.key] = list(result.documents)
                    statuses.append(SourceStatus(source=plan.key, state="success", documents_count=result.documents_count))
                else:
                    statuses.append(SourceStatus(source=plan.key, state="failed", detail=_short("; ".join(result.errors))))
        return statuses, documents

    async def run(self, config: Configuration) -> None:
        """Process one configuration and persist its final status. Never raises."""
        try:
            config.status = "processing"
            self._store.save(config)
            statuses, documents = await self._read(config, self._plan(config))
            for source, items in documents.items():
                self._store.save_documents(config.id, source, items)  # kept, so another connector can be added later

            config.sources = statuses
            problems = [f"{SPECS[x.source].label}: {x.detail}" for x in statuses if x.state != "success"]
            if not problems:
                # every selected connector was read: only then is the context complete enough for a graph
                self._build_graph(config, [d for items in documents.values() for d in items])
                config.status = "ready"
                config.status_detail = self._ontology_note(config)
            else:
                config.status = "failed"
                config.status_detail = _short("; ".join(problems))
        except ConsoleError as exc:  # the ontology could not be loaded: nothing is shown that was not checked against it
            config.status = "failed"
            config.status_detail = _short(exc.message)
        except Exception as exc:  # fail closed: record, never leak internals
            logger.error("config.process_failed", configuration_id=config.id, error=type(exc).__name__)
            config.status = "failed"
            config.status_detail = "Processing failed unexpectedly. See the service log."
        finally:
            self._secrets.drop(config.id)
        self._store.save(config)
        await self._record(config, "configuration.process")

    async def run_added(self, config: Configuration, added: list[str]) -> None:
        """Add connectors to a configuration that is already ready. Never raises.

        Only the new connectors are read. The earlier ones are not read again: their tokens are not kept, so the graph is
        rebuilt from what they returned the first time. A new connector that cannot be read is taken out again, and the
        configuration stays ready with the graph it had, plus a note saying what could not be added.
        """
        previous = [k for k, c in config.connectors.items() if c.enabled and k not in added]
        old_statuses = [s for s in (config.sources or []) if s.source in previous]
        try:
            saved: dict[str, list[SourceDocument]] = {}
            for key in previous:
                items = self._store.load_documents(config.id, key)
                if items is None:
                    self._revert(config, added, f"The saved results for {SPECS[key].label} are missing, so the graph cannot include it. Use Edit and resubmit to read everything again.")
                    return await self._finish_added(config, old_statuses)
                saved[key] = items

            plans = self._plan(config)
            for unused in (p for p in plans if p.key not in added and p.client is not None):
                await unused.client.aclose()  # type: ignore[union-attr] -- an earlier connector that uses the server's credentials
            statuses, documents = await self._read(config, [p for p in plans if p.key in added])
            failed = [s for s in statuses if s.state != "success"]
            for source, items in documents.items():
                self._store.save_documents(config.id, source, items)
            if failed:
                self._revert(config, [s.source for s in failed], "; ".join(f"Could not add {SPECS[s.source].label}: {s.detail}" for s in failed))
            kept = [s for s in statuses if s.state == "success"]
            if kept:
                self._build_graph(config, [d for items in (saved | documents).values() for d in items])
            return await self._finish_added(config, old_statuses + kept)
        except Exception as exc:  # fail closed: the graph it had stays, nothing half-added
            logger.error("config.add_failed", configuration_id=config.id, error=type(exc).__name__)
            self._revert(config, added, "Adding a connector failed unexpectedly. See the service log.")
            return await self._finish_added(config, old_statuses)
        finally:
            self._secrets.drop(config.id)

    def _build_graph(self, config: Configuration, documents: list[SourceDocument]) -> None:
        """Propose the graph from the documents, keep what the ontology allows, save it, and pin the ontology on the configuration."""
        graph, pin = apply_ontology(self._s, build_graph(config.id, documents))
        self._store.save_graph(graph)
        config.ontology = pin

    @staticmethod
    def _ontology_note(config: Configuration) -> str | None:
        pin = config.ontology
        if pin and (pin.nodes_dropped or pin.edges_dropped):
            return _short(f"{pin.nodes_dropped} item(s) and {pin.edges_dropped} relationship(s) were left out because the ontology does not allow them.")
        return None

    @staticmethod
    def _revert(config: Configuration, keys: list[str], detail: str) -> None:
        for key in keys:
            config.connectors[key] = ConnectorSummary(enabled=False)
        config.status_detail = _short(detail)

    async def _finish_added(self, config: Configuration, statuses: list[SourceStatus]) -> None:
        config.sources = statuses
        config.status = "ready"
        self._store.save(config)
        await self._record(config, "configuration.add_connectors")

    async def _record(self, config: Configuration, action: str) -> None:
        await self._audit.record(
            AuditEvent(
                source="console", action=action, status=config.status, at=datetime.now(UTC),
                details={"configuration_id": config.id, "tenant_id": config.tenant_id},
            )
        )
