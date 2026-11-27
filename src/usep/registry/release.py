"""Release format. One release is one core version or one pack version: a signed manifest plus a bundle of its files.

Signed body (deterministic, no timestamps): schema, kind, id, version, requires_core, level, reference_only, the sha256 of
every file, a content digest of those, and the sha256 of the bundle. The bundle is a stored (uncompressed) zip with files in
sorted order and fixed timestamps, so the same files always give the same bytes.
Paths inside a bundle are relative to the ontology root (`core/...`, `templates/...`, `packs/app/<pack>/...`), so unpacking a
core bundle and its pack bundles into one directory rebuilds a tree the loader reads with no changes. That is also why the
loader's digest of a registry-loaded ontology equals the digest of the same files in Git.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from usep.registry.errors import RegistryError

SCHEMA = 1
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_LEVEL_DIR = {"industry": "industry", "organization": "org", "application": "app", "project": "project"}
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(body: dict[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def content_digest(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode() + b"\0" + bytes.fromhex(files[path]))
    return h.hexdigest()


@dataclass(frozen=True)
class Release:
    body: dict[str, Any]          # the signed body
    bundle: bytes                 # zip of the files

    @property
    def kind(self) -> str:
        return self.body["kind"]

    @property
    def id(self) -> str:
        return self.body["id"]

    @property
    def version(self) -> str:
        return self.body["version"]


def _read_yaml(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _collect(root: Path, folders: list[Path], extra: list[Path] = ()) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for base in folders:
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name != ".gitkeep" and "__pycache__" not in p.parts:
                files[p.relative_to(root).as_posix()] = p.read_bytes().replace(b"\r\n", b"\n")
    for p in extra:
        files[p.relative_to(root).as_posix()] = p.read_bytes().replace(b"\r\n", b"\n")
    return files


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, _FIXED_TIME)
            info.external_attr = 0o644 << 16
            z.writestr(info, files[path])
    return buf.getvalue()


def _release(kind: str, manifest: dict[str, Any], files: dict[str, bytes]) -> Release:
    version = str(manifest.get("version", ""))
    if not _SEMVER.match(version):
        raise RegistryError(f"{manifest.get('id')}: version {version!r} is not major.minor.patch")
    hashes = {p: sha256(b) for p, b in files.items()}
    bundle = _zip(files)
    body = {"schema": SCHEMA, "kind": kind, "id": str(manifest["id"]), "version": version,
            "requires_core": manifest.get("requires_core"), "level": manifest.get("level"),
            "reference_only": manifest.get("reference_only") is True, "files": hashes,
            "digest": content_digest(hashes), "bundle_sha256": sha256(bundle)}
    return Release(body, bundle)


def build_core_release(root: str | Path) -> Release:
    root = Path(root)
    mf = _read_yaml(root / "core" / "pack.yml")
    files = _collect(root, [root / "core", root / "templates"], sorted((root / "shapes").glob("*.ttl")))
    return _release("core", mf, files)


def find_pack_dir(root: Path, pack_id: str) -> Path:
    for folder in _LEVEL_DIR.values():
        base = root / "packs" / folder
        for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
            if (d / "pack.yml").is_file() and _read_yaml(d / "pack.yml").get("id") == pack_id:
                return d
    raise RegistryError(f"pack not found: {pack_id}")


def build_pack_release(root: str | Path, pack_id: str) -> Release:
    root = Path(root)
    d = find_pack_dir(root, pack_id)
    mf = _read_yaml(d / "pack.yml")
    if _LEVEL_DIR.get(mf.get("level", ""), "?") != d.parent.name:
        raise RegistryError(f"{pack_id}: level {mf.get('level')!r} does not match folder {d.parent.name!r}")
    return _release("pack", mf, _collect(root, [d]))


def all_pack_ids(root: str | Path) -> list[str]:
    root = Path(root)
    out = []
    for folder in _LEVEL_DIR.values():
        base = root / "packs" / folder
        for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
            if (d / "pack.yml").is_file():
                out.append(str(_read_yaml(d / "pack.yml")["id"]))
    return out


def check_body_against_bundle(body: dict[str, Any], bundle: bytes) -> dict[str, bytes]:
    """The files in the bundle are exactly the files the signed body names, byte for byte. Returns them."""
    if sha256(bundle) != body.get("bundle_sha256"):
        raise RegistryError(f"{body.get('id')}@{body.get('version')}: bundle does not match its manifest")
    try:
        z = zipfile.ZipFile(io.BytesIO(bundle))
    except zipfile.BadZipFile as exc:
        raise RegistryError(f"{body.get('id')}: bundle is not a zip") from exc
    files = {}
    for info in z.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts or "\\" in name:
            raise RegistryError(f"{body.get('id')}: unsafe path in bundle: {name!r}")     # zip-slip
        files[name] = z.read(info)
    if {p: sha256(b) for p, b in files.items()} != body.get("files") or content_digest(body["files"]) != body.get("digest"):
        raise RegistryError(f"{body.get('id')}@{body.get('version')}: files differ from the signed manifest")
    return files
