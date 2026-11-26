"""Three pagination shapes, one async generator each, so a connector's own fetch
loop looks identical regardless of which shape its source uses (section 5.7, 9).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

from usep.core.errors import PaginationError

T = TypeVar("T")

DEFAULT_MAX_PAGES = 10_000


async def paginate_cursor[T](
    fetch_page: Callable[[str | None], Awaitable[tuple[list[T], str | None]]],
    start_cursor: str | None = None,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> AsyncIterator[list[T]]:
    """`fetch_page(cursor) -> (items, next_cursor)`.

    Stops when `next_cursor` is `None`. Raises `PaginationError` if the same cursor
    is seen twice (a source bug or an infinite loop) or `max_pages` is exceeded.
    """
    cursor = start_cursor
    seen: set[str] = set()
    pages = 0
    while True:
        pages += 1
        if pages > max_pages:
            raise PaginationError(f"exceeded max_pages={max_pages}")
        items, next_cursor = await fetch_page(cursor)
        yield items
        if next_cursor is None:
            return
        if next_cursor in seen:
            raise PaginationError(f"repeated cursor: {next_cursor!r}")
        seen.add(next_cursor)
        cursor = next_cursor


async def paginate_offset[T](
    fetch_page: Callable[[int, int], Awaitable[tuple[list[T], int | None]]],
    *,
    page_size: int = 100,
) -> AsyncIterator[list[T]]:
    """`fetch_page(start, page_size) -> (items, total)`.

    Stops on an empty page, or once `start` reaches or passes `total` when the
    source reports one.
    """
    start = 0
    while True:
        items, total = await fetch_page(start, page_size)
        if not items:
            return
        yield items
        start += len(items)
        if total is not None and start >= total:
            return


async def paginate_link_header[T](
    fetch_page: Callable[[str | None], Awaitable[tuple[list[T], str | None]]],
    start_url: str | None = None,
) -> AsyncIterator[list[T]]:
    """`fetch_page(url) -> (items, next_url)`, where `next_url` is the target of a
    `rel="next"` Link header, or `None` at the end."""
    url = start_url
    while True:
        items, next_url = await fetch_page(url)
        yield items
        if next_url is None:
            return
        url = next_url
