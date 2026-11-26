from __future__ import annotations

import httpx
import pytest

from figma.client import FigmaClient
from figma.connector import FigmaConnector, parse_scope


def test_parse_scope() -> None:
    assert parse_scope("AbC123") == ("AbC123", [])
    assert parse_scope("https://www.figma.com/design/AbC123/Name?node-id=1-2") == ("AbC123", ["1:2"])
    with pytest.raises(ValueError):
        parse_scope("https://www.figma.com/community/plugin/1")


FILE = {
    "name": "App",
    "version": "99",
    "lastModified": "2026-11-26T10:00:00Z",
    "document": {
        "children": [
            {
                "id": "0:1",
                "type": "CANVAS",
                "name": "Checkout",
                "children": [
                    {"id": "5:1", "type": "SECTION", "children": [
                        {"id": "5:2", "type": "FRAME", "name": "Pay", "children": [{"id": "5:3", "type": "TEXT", "name": "t", "characters": "Pay now"}]}
                    ]},
                    {"id": "6:1", "type": "RECTANGLE"},
                ],
            }
        ]
    },
}


def _handler(calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.url.path}?{request.url.query.decode()}")
        if request.url.path == "/v1/files/KEY":
            return httpx.Response(200, json=FILE)
        if request.url.path == "/v1/images/KEY":
            return httpx.Response(200, json={"images": {"5:2": "https://s3.example/render.png"}})
        raise AssertionError(request.url)

    return handler


async def test_finds_frames_inside_sections_and_exports_them() -> None:
    calls: list[str] = []
    client = FigmaClient("https://api.figma.com", "token", transport=httpx.MockTransport(_handler(calls)))
    result = await FigmaConnector(client, ["KEY"]).fetch_scope("KEY", None)

    doc = result.documents[0]
    assert [f.node_id for f in doc.frames] == ["5:2"]
    assert doc.frames[0].page_name == "Checkout"
    assert doc.text_layers[0].characters == "Pay now"
    assert doc.frames[0].export_refs[0].url == "https://s3.example/render.png"
    assert doc.source_version == "2026-11-26T10:00:00.000Z"


async def test_unchanged_file_is_skipped_after_cheap_check() -> None:
    calls: list[str] = []
    client = FigmaClient("https://api.figma.com", "token", transport=httpx.MockTransport(_handler(calls)))
    result = await FigmaConnector(client, ["KEY"]).fetch_scope("KEY", "2026-11-26T10:00:00.000Z")

    assert result.documents == [] and result.errors == []
    assert calls == ["/v1/files/KEY?depth=1"]
