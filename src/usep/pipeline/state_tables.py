"""Which source field feeds which core attribute, and which project-pack table translates it.

Which attribute a concept's state feeds is a core fact (ontology/core/concepts.yml). The table that translates the
source's values is the project pack's (ontology/packs/project/*/workflow.yml). This module is the join between them.
To translate a new source: add a row here, and the tables to the project pack.
"""
from __future__ import annotations

STATE_TABLES = (
    # (source system, concept, target attribute, field of the source object, project-pack table)
    ("jira", "Change", "change_state", "status", "issue_workflow"),
    ("jira", "Requirement", "status", "status", "requirement_status"),
    ("jira", "Incident", "severity", "priority", "jira_incident_severity"),
    ("jira", "Incident", "status", "status", "jira_incident_status"),
    ("git", "Change", "change_state", "state", "pull_request_workflow"),
    ("servicenow", "Change", "change_state", "state", "servicenow_change_workflow"),
    ("servicenow", "Incident", "severity", "priority", "servicenow_incident_severity"),
    ("servicenow", "Incident", "status", "state", "servicenow_incident_status"),
    ("ado", "Change", "change_state", "state", "ado_workitem_workflow"),
    ("ado", "Requirement", "status", "state", "ado_requirement_status"),
)
