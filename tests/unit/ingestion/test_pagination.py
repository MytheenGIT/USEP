from __future__ import annotations

import pytest

from usep.core.errors import PaginationError
from usep.ingestion.runtime.pagination import paginate_cursor, paginate_link_header, paginate_offset


@pytest.mark.asyncio
async def test_pagination_repeated_cursor_raises() -> None:
    pages = {None: (["a"], "c1"), "c1": (["b"], "c1")}  # c1 repeats: a source bug or a loop

    async def fetch_page(cursor: str | None) -> tuple[list[str], str | None]:
        return pages[cursor]

    collected: list[str] = []
    with pytest.raises(PaginationError, match="repeated cursor"):
        async for page in paginate_cursor(fetch_page):
            collected.extend(page)
    assert collected == ["a", "b"]


@pytest.mark.asyncio
async def test_pagination_cursor_stops_at_max_pages() -> None:
    counter = {"n": 0}

    async def fetch_page(cursor: str | None) -> tuple[list[int], str | None]:
        counter["n"] += 1
        return [counter["n"]], str(counter["n"])

    with pytest.raises(PaginationError, match="max_pages"):
        async for _ in paginate_cursor(fetch_page, max_pages=3):
            pass
    assert counter["n"] == 3  # three pages fetched; the loop raises before a 4th fetch


@pytest.mark.asyncio
async def test_pagination_cursor_stops_cleanly_when_next_is_none() -> None:
    pages = {None: (["a", "b"], "c1"), "c1": (["c"], None)}

    async def fetch_page(cursor: str | None) -> tuple[list[str], str | None]:
        return pages[cursor]

    collected: list[str] = []
    async for page in paginate_cursor(fetch_page):
        collected.extend(page)
    assert collected == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_pagination_offset_and_link_helpers() -> None:
    # Offset: stops once start >= total.
    all_items = list(range(25))

    async def fetch_offset(start: int, page_size: int) -> tuple[list[int], int | None]:
        return all_items[start : start + page_size], len(all_items)

    collected: list[int] = []
    async for page in paginate_offset(fetch_offset, page_size=10):
        collected.extend(page)
    assert collected == all_items

    # Offset: stops on an empty page even with no total reported.
    async def fetch_offset_no_total(start: int, page_size: int) -> tuple[list[int], int | None]:
        items = all_items[start : start + page_size]
        return items, None

    collected_no_total: list[int] = []
    async for page in paginate_offset(fetch_offset_no_total, page_size=10):
        collected_no_total.extend(page)
    assert collected_no_total == all_items

    # Link header: follows rel="next" until None.
    link_pages = {None: (["x"], "/page2"), "/page2": (["y"], "/page3"), "/page3": (["z"], None)}

    async def fetch_link(url: str | None) -> tuple[list[str], str | None]:
        return link_pages[url]

    collected_links: list[str] = []
    async for page in paginate_link_header(fetch_link):
        collected_links.extend(page)
    assert collected_links == ["x", "y", "z"]


@pytest.mark.asyncio
async def test_pagination_link_header_repeated_url_raises() -> None:
    pages = {None: (["x"], "/page2"), "/page2": (["y"], "/page2")}

    async def fetch_link(url: str | None) -> tuple[list[str], str | None]:
        return pages[url]

    with pytest.raises(PaginationError, match="repeated link"):
        async for _ in paginate_link_header(fetch_link):
            pass


@pytest.mark.asyncio
async def test_pagination_link_header_stops_at_max_pages() -> None:
    counter = {"n": 0}

    async def fetch_link(url: str | None) -> tuple[list[int], str | None]:
        counter["n"] += 1
        return [counter["n"]], f"/page{counter['n']}"

    with pytest.raises(PaginationError, match="max_pages"):
        async for _ in paginate_link_header(fetch_link, max_pages=3):
            pass
    assert counter["n"] == 3


@pytest.mark.asyncio
async def test_pagination_offset_stops_at_max_pages_when_source_ignores_start() -> None:
    async def fetch_offset(start: int, page_size: int) -> tuple[list[int], int | None]:
        return [1, 2, 3], None

    with pytest.raises(PaginationError, match="max_pages"):
        async for _ in paginate_offset(fetch_offset, max_pages=3):
            pass
