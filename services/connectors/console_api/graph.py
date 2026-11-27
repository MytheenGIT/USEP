"""Project ingested documents into a knowledge-graph view for the UI.

This is a PROVISIONAL, rule-based projection of what connectors fetched. It is not the ontology
extraction or the labelling pipeline (those are later phases). It only uses explicit evidence:
a merge request that names a Jira key implements that issue. Mappings to ontology concepts
are proposals; inferred ones carry a confidence below 1 so the UI marks them.
"""

from __future__ import annotations

import re
from typing import Any

from common.source_document import SourceDocument
from console_api.ids import utc_now_iso
from console_api.models import Graph, GraphEdge, GraphNode

ONTOLOGY_VERSION = "0.1.0"  # ontology/core/pack.yml
JIRA_KEY_IN_TEXT = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")
ADR_TITLE = re.compile(r"\bADR[-\s]?\d+", re.IGNORECASE)
INFERRED_CONFIDENCE = 0.6


def _issue_type(doc: SourceDocument) -> str:
    fields = doc.raw_payload.get("fields") if isinstance(doc.raw_payload, dict) else None
    issuetype = (fields or {}).get("issuetype") or {}
    return str(issuetype.get("name") or "Issue")


def _text(doc: Any) -> str:
    """Everything in a code change that may name a Jira issue: title, description and commit messages."""
    parts = [doc.title or "", getattr(doc, "description", None) or "", getattr(doc, "message", None) or ""]
    parts += [c.message for c in getattr(doc, "commits", [])]
    return "\n".join(parts)


CHANGE_NUMBER = re.compile(r"\bCHG\d{4,}\b")


def _record_text(doc: Any) -> str:
    return "\n".join([doc.title or "", getattr(doc, "description", None) or ""])


def build_graph(configuration_id: str, documents: list[SourceDocument]) -> Graph:
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    def add_edge(source: str, target: str, relation: str, confidence: float, evidence: str, system: str) -> None:
        edge_id = f"{source}-{relation}-{target}"
        edges[edge_id] = GraphEdge(id=edge_id, source=source, target=target, relation=relation, confidence=confidence, evidence_ref=evidence, source_system=system)

    for doc in documents:
        if doc.source.value != "jira":
            continue
        issue_type = _issue_type(doc)
        is_bug = issue_type.lower() == "bug"
        node_id = f"jira:{doc.source_object_id}"
        nodes[node_id] = GraphNode(
            id=node_id,
            concept="Incident" if is_bug else "Requirement",
            name=f"{doc.source_object_id} {doc.title}".strip(),
            labels=[issue_type],
            properties={"status": getattr(doc, "status", ""), "priority": getattr(doc, "priority", None), "url": doc.source_url},
            source_system="jira",
            source_id=doc.source_object_id,
            confidence=INFERRED_CONFIDENCE if is_bug else None,
            ontology_version=ONTOLOGY_VERSION,
        )

    # Code changes: a GitLab merge request, a GitHub pull request, or a commit read over SSH. One that names a Jira issue
    # key implements that issue (explicit evidence, so confidence 1).
    for doc in documents:
        source = doc.source.value
        is_change = (source == "gitlab" and doc.source_type == "merge_request") or (source == "github" and doc.source_type == "pull_request") or doc.source_type == "commit"
        if is_change:
            kind = {"merge_request": "merge_request", "pull_request": "pull_request", "commit": "commit"}[doc.source_type]
            node_id = f"{source}:{doc.source_object_id}"
            label = {"merge_request": "MR", "pull_request": "PR", "commit": "Commit"}[doc.source_type]
            ref = doc.source_object_id if doc.source_type != "commit" else doc.source_object_id.split("@")[0] + "@" + doc.source_object_id.split("@")[-1][:8]
            nodes[node_id] = GraphNode(
                id=node_id, concept="Change", name=f"{label} {ref} {doc.title}".strip(), labels=[kind],
                properties={"state": getattr(doc, "state", ""), "url": doc.source_url}, source_system=source,
                source_id=doc.source_object_id, ontology_version=ONTOLOGY_VERSION,
            )
            for key in sorted(set(JIRA_KEY_IN_TEXT.findall(_text(doc)))):
                target = f"jira:{key}"
                if target in nodes and nodes[target].concept == "Requirement":
                    add_edge(node_id, target, "implements", 1.0, doc.source_url, source)
        elif source == "confluence" and ADR_TITLE.search(doc.title or ""):
            node_id = f"confluence:{doc.source_object_id}"
            nodes[node_id] = GraphNode(
                id=node_id, concept="Decision", name=doc.title, labels=["adr"],
                properties={"space": getattr(doc, "space_key", ""), "url": doc.source_url},
                source_system="confluence", source_id=doc.source_object_id, confidence=INFERRED_CONFIDENCE,
                ontology_version=ONTOLOGY_VERSION,
            )
        elif source == "servicenow":
            table = getattr(doc, "table", "")
            if table in ("incident", "problem"):
                concept, labels = "Incident", [table]
            elif table == "change_request":
                concept, labels = "Change", ["change_request"]
            else:
                continue
            node_id = f"servicenow:{doc.source_object_id}"
            nodes[node_id] = GraphNode(
                id=node_id, concept=concept, name=f"{doc.number} {doc.title}".strip(), labels=labels,
                properties={"state": getattr(doc, "state", None), "priority": getattr(doc, "priority", None), "group": getattr(doc, "assignment_group", None), "url": doc.source_url},
                source_system="servicenow", source_id=doc.source_object_id, confidence=INFERRED_CONFIDENCE if concept == "Incident" else None,
                ontology_version=ONTOLOGY_VERSION,
            )

    # ServiceNow records that name a Jira issue or a change request: the change implements the issue (explicit), and an
    # incident that names a change request was probably caused by it (inferred, so a lower confidence).
    by_number = {n.source_id.split(":", 1)[-1]: n.id for n in nodes.values() if n.source_system == "servicenow" and n.concept == "Change" and n.source_id}
    for doc in documents:
        if doc.source.value != "servicenow":
            continue
        node_id = f"servicenow:{doc.source_object_id}"
        if node_id not in nodes:
            continue
        text = _record_text(doc)
        if nodes[node_id].concept == "Change":
            for key in sorted(set(JIRA_KEY_IN_TEXT.findall(text))):
                target = f"jira:{key}"
                if target in nodes and nodes[target].concept == "Requirement":
                    add_edge(node_id, target, "implements", 1.0, doc.source_url, "servicenow")
        else:
            for number in sorted(set(CHANGE_NUMBER.findall(text))):
                if number in by_number:
                    add_edge(node_id, by_number[number], "caused_by", INFERRED_CONFIDENCE, doc.source_url, "servicenow")

    return Graph(
        configuration_id=configuration_id,
        generated_at=utc_now_iso(),
        ontology_version=ONTOLOGY_VERSION,
        nodes=list(nodes.values()),
        edges=list(edges.values()),
    )
