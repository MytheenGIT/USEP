"""Configuration store on local JSON files until Postgres lands (ontology-registry migrations own the real schema).

Layout: <output_dir>/configurations/<id>/{configuration.json,graph.json,runs/<source>/*.json}.
Swap this class for a Postgres-backed one behind the same methods; callers do not change.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from common.source_document import SourceDocument
from console_api.documents import dump_documents, load_documents
from console_api.models import Configuration, Graph

_ID = re.compile(r"^[0-9a-f-]{36}$")


class ConfigurationStore:
    def __init__(self, output_dir: str) -> None:
        self._root = Path(output_dir) / "configurations"
        self._lock = threading.Lock()

    def directory(self, config_id: str) -> Path:
        if not _ID.match(config_id):
            raise KeyError(config_id)
        return self._root / config_id

    def save(self, config: Configuration) -> None:
        with self._lock:
            directory = self.directory(config.id)
            directory.mkdir(parents=True, exist_ok=True)
            tmp = directory / "configuration.json.tmp"
            tmp.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(directory / "configuration.json")

    def get(self, tenant_id: str, config_id: str) -> Configuration | None:
        try:
            path = self.directory(config_id) / "configuration.json"
        except KeyError:
            return None
        if not path.is_file():
            return None
        try:
            config = Configuration.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:  # saved by an older version of the schema
            return None
        return config if config.tenant_id == tenant_id else None

    def list(self, tenant_id: str) -> list[Configuration]:
        if not self._root.is_dir():
            return []
        items = []
        for path in self._root.glob("*/configuration.json"):
            try:
                config = Configuration.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if config.tenant_id == tenant_id:
                items.append(config)
        return sorted(items, key=lambda c: c.created_at, reverse=True)

    def save_documents(self, config_id: str, source: str, documents: list[SourceDocument]) -> None:
        """What one source returned for this configuration (readable JSON), so the graph can be rebuilt without reading it again."""
        directory = self.directory(config_id) / "sources"
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f"{source}.json.tmp"
        tmp.write_text(json.dumps(dump_documents(documents), ensure_ascii=False), encoding="utf-8")
        tmp.replace(directory / f"{source}.json")

    def load_documents(self, config_id: str, source: str) -> list[SourceDocument] | None:
        """The saved documents of one source, or None when there are none or they cannot be read back."""
        path = self.directory(config_id) / "sources" / f"{source}.json"
        if not path.is_file():
            return None
        try:
            return load_documents(source, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def save_graph(self, graph: Graph) -> None:
        directory = self.directory(graph.configuration_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "graph.json").write_text(graph.model_dump_json(indent=2), encoding="utf-8")

    def get_graph(self, config_id: str) -> Graph | None:
        path = self.directory(config_id) / "graph.json"
        return Graph.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

    def mark_interrupted(self) -> None:
        """A restart kills in-flight jobs: show them as failed instead of processing forever."""
        for path in self._root.glob("*/configuration.json") if self._root.is_dir() else []:
            try:
                config = Configuration.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if config.status in ("submitted", "processing"):
                config.status = "failed"
                config.status_detail = "Processing was interrupted by a service restart. Submit the configuration again."
                self.save(config)
