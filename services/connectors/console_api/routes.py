"""The /api routes the UI calls (contract: ui/README.md)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request, Response

from usep.ingestion.ports.audit import AuditEvent
from console_api.auth import Session, bearer_token, credentials_match, require_session
from console_api.errors import ConsoleError
from console_api.ids import utc_now_iso, uuid7
from console_api.connectivity import check_connection
from console_api.ontology import ontology_dto, ontology_graph
from console_api.models import (
    Configuration, ConnectorDefault, Graph, LoginBody, RepositoryList, SessionOut, ConnectionCheck,
)
from console_api.repositories import RepositoryListError, list_repositories
from console_api.secrets_store import Credentials
from console_api.validation import FIGMA_DPIA_MESSAGE, SPECS, parse_config, parse_connector, server_base_url, server_credentials

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["console"])


async def _audit(request: Request, action: str, status: str, actor: str, **details: Any) -> None:
    try:
        await request.app.state.audit.record(
            AuditEvent(source="console", action=action, status=status, at=datetime.now(UTC), details={
                "actor": actor, "request_id": getattr(request.state, "request_id", None),
                "client_ip": request.client.host if request.client else None, **details,
            })
        )
    except Exception as exc:  # noqa: BLE001 -- an audit store problem is logged, it does not break the admin's request
        logger.warning("console.audit_failed", action=action, error=type(exc).__name__)


def _client_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}|{username.lower()}"


@router.post("/auth/login", response_model=SessionOut)
async def login(body: LoginBody, request: Request) -> SessionOut:
    state, settings = request.app.state, request.app.state.settings
    key = _client_key(request, body.username)
    state.throttle.check(key)
    if not credentials_match(settings.admin_username, settings.admin_password, body.username, body.password):
        state.throttle.fail(key)
        await _audit(request, "auth.login", "denied", body.username[:64])
        raise ConsoleError(401, "invalid_credentials", "Invalid username or password")
    state.throttle.reset(key)
    session = state.sessions.create(body.username)
    await _audit(request, "auth.login", "success", body.username[:64])
    return SessionOut(token=session.token, username=session.username)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, session: Session = Depends(require_session)) -> Response:
    token = bearer_token(request)
    if token:
        request.app.state.sessions.revoke(token)
    await _audit(request, "auth.logout", "success", session.username)
    return Response(status_code=204)


@router.get("/configurations", response_model=list[Configuration])
async def list_configurations(request: Request, session: Session = Depends(require_session)) -> list[Configuration]:
    return request.app.state.store.list(str(request.app.state.settings.tenant_id))


@router.get("/connector-defaults", response_model=dict[str, ConnectorDefault])
async def connector_defaults(request: Request, session: Session = Depends(require_session)) -> dict[str, ConnectorDefault]:
    settings = request.app.state.settings
    return {
        key: ConnectorDefault(
            base_url=(server_base_url(settings, key) or None) if spec.needs_base_url else None,
            credentials_configured=server_credentials(settings, key) is not None,
            blocked_reason=FIGMA_DPIA_MESSAGE if key == "figma" and not settings.figma.dpia_approved else None,
            ssh_available=spec.supports_ssh,
        )
        for key, spec in SPECS.items()
    }


@router.post("/connectors/{source}/test", response_model=ConnectionCheck)
async def test_connector(
    source: str, payload: dict[str, Any], request: Request, session: Session = Depends(require_session)
) -> ConnectionCheck:
    spec = SPECS.get(source)
    if spec is None:
        raise ConsoleError(404, "not_found", "Unknown connector")
    settings = request.app.state.settings
    errors: dict[str, str] = {}
    parsed = await parse_connector(spec, payload, settings, errors, require_targets=False)
    if errors:
        raise ConsoleError(422, "validation_failed", "Check the highlighted fields", errors)
    result = await check_connection(spec, parsed, settings, request.app.state.runtime_for)
    await _audit(request, "connector.test", "success" if result.ok else "failed", session.username, connector=source)
    return result


@router.post("/connectors/{source}/repositories", response_model=RepositoryList)
async def connector_repositories(
    source: str, payload: dict[str, Any], request: Request, session: Session = Depends(require_session)
) -> RepositoryList:
    """The repositories the entered token can reach (GitHub and GitLab), for choosing from."""
    spec = SPECS.get(source)
    if spec is None or not spec.supports_all:
        raise ConsoleError(404, "not_found", "That connector has no repositories to choose from")
    errors: dict[str, str] = {}
    parsed = await parse_connector(spec, payload, request.app.state.settings, errors, require_targets=False)
    if errors:
        raise ConsoleError(422, "validation_failed", "Check the highlighted fields", errors)
    try:
        result = await list_repositories(spec, parsed, request.app.state.settings, request.app.state.runtime_for)
    except RepositoryListError as exc:
        await _audit(request, "connector.repositories", "failed", session.username, connector=source)
        raise ConsoleError(422, "repositories_unavailable", str(exc)) from exc
    await _audit(request, "connector.repositories", "success", session.username, connector=source, count=len(result.repositories))
    return result


@router.post("/configurations", response_model=Configuration, status_code=201)
async def create_configuration(
    payload: dict[str, Any], request: Request, session: Session = Depends(require_session)
) -> Configuration:
    state = request.app.state
    parsed, errors = await parse_config(payload, state.settings)
    if errors:
        raise ConsoleError(422, "validation_failed", "Check the highlighted fields", errors)
    config = Configuration(
        id=uuid7(), tenant_id=str(state.settings.tenant_id), name=parsed.name, status="submitted",
        created_at=utc_now_iso(), created_by=session.username,
        connectors={k: v.summary for k, v in parsed.connectors.items()},
    )
    for key, connector in parsed.connectors.items():
        if connector.credentials is not None:
            state.secrets.put(config.id, key, Credentials(connector.credentials.email, connector.credentials.secret, connector.credentials.ssh_key))
    state.store.save(config)
    await _audit(
        request, "configuration.create", "success", session.username, configuration_id=config.id,
        tenant_id=config.tenant_id, connectors=[k for k, v in config.connectors.items() if v.enabled],
    )
    task = asyncio.create_task(state.processor.run(config.model_copy(deep=True)))
    state.background_tasks.add(task)
    task.add_done_callback(state.background_tasks.discard)
    return config


@router.post("/configurations/{config_id}/connectors", response_model=Configuration)
async def add_connectors(
    config_id: str, payload: dict[str, Any], request: Request, session: Session = Depends(require_session)
) -> Configuration:
    """Add connectors to a configuration that is ready. Only the new ones are read; the graph is rebuilt from saved results."""
    state = request.app.state
    config = _get_or_404(request, config_id)
    if config.status != "ready":
        raise ConsoleError(409, "not_ready", "A connector can be added once the configuration is ready. Use Edit and resubmit instead.")
    sections = payload.get("connectors")
    sections = sections if isinstance(sections, dict) else {}
    errors: dict[str, str] = {}
    added: dict[str, Any] = {}
    already: list[str] = []
    for key, spec in SPECS.items():
        section = sections.get(key)
        if not isinstance(section, dict) or section.get("enabled") is not True:
            continue
        existing = config.connectors.get(key)
        if existing is not None and existing.enabled:
            already.append(spec.label)
            continue
        added[key] = await parse_connector(spec, section, state.settings, errors)
    if already:
        errors["connectors"] = f"{', '.join(already)} {'is' if len(already) == 1 else 'are'} already in this configuration"
    elif not added:
        errors["connectors"] = "Select at least one connector to add"
    if errors:
        raise ConsoleError(422, "validation_failed", "Check the highlighted fields", errors)
    for key, parsed in added.items():
        config.connectors[key] = parsed.summary
        if parsed.credentials is not None:
            state.secrets.put(config.id, key, Credentials(parsed.credentials.email, parsed.credentials.secret, parsed.credentials.ssh_key))
    config.status, config.status_detail = "processing", None
    state.store.save(config)
    await _audit(request, "configuration.add_connectors", "success", session.username, configuration_id=config.id, tenant_id=config.tenant_id, connectors=list(added))
    task = asyncio.create_task(state.processor.run_added(config.model_copy(deep=True), list(added)))
    state.background_tasks.add(task)
    task.add_done_callback(state.background_tasks.discard)
    return config


def _get_or_404(request: Request, config_id: str) -> Configuration:
    config = request.app.state.store.get(str(request.app.state.settings.tenant_id), config_id)
    if config is None:
        raise ConsoleError(404, "not_found", "Configuration not found")
    return config


@router.get("/configurations/{config_id}", response_model=Configuration)
async def get_configuration(config_id: str, request: Request, session: Session = Depends(require_session)) -> Configuration:
    return _get_or_404(request, config_id)


@router.get("/configurations/{config_id}/graph", response_model=Graph)
async def get_graph(config_id: str, request: Request, session: Session = Depends(require_session)) -> Graph:
    config = _get_or_404(request, config_id)
    if config.status != "ready":
        raise ConsoleError(409, "graph_not_ready", "The knowledge graph is not ready yet")
    graph = request.app.state.store.get_graph(config.id)
    if graph is None:
        raise ConsoleError(409, "graph_not_ready", "The knowledge graph is not ready yet")
    await _audit(request, "graph.read", "success", session.username, configuration_id=config.id, tenant_id=config.tenant_id)
    return graph


@router.get("/configurations/{config_id}/ontology")
async def get_ontology(config_id: str, request: Request, session: Session = Depends(require_session)) -> dict[str, Any]:
    """The ontology this configuration is pinned to (definitions only; contract: docs/ui-ontology-view-brief.md)."""
    config = _get_or_404(request, config_id)
    out = ontology_dto(request.app.state.settings)
    await _audit(request, "ontology.read", "success", session.username, configuration_id=config.id, ontology_digest=out["digest"][:12])
    return out


@router.get("/configurations/{config_id}/ontology/graphify")
async def get_ontology_graphify(config_id: str, request: Request, session: Session = Depends(require_session)) -> dict[str, Any]:
    """The same ontology as a Graphify graph.json (concepts are nodes, relationship types are links)."""
    config = _get_or_404(request, config_id)
    out = ontology_graph(request.app.state.settings)
    await _audit(request, "ontology.graph.read", "success", session.username, configuration_id=config.id,
                 ontology_digest=out["graph"]["ontology_digest"][:12])
    return out
