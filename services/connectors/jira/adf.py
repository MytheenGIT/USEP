"""Atlassian Document Format (ADF) to Markdown.

Headings, lists, code blocks, tables and panels are kept as Markdown
structure so the chunker can split a description by heading and pick out
acceptance-criteria blocks (spec Module 3; semantic layer design Section 3:
"ADF to Markdown, then MarkdownHeaderTextSplitter"). Unknown node types fall
back to their children's text, so content is never dropped.
"""

from __future__ import annotations

from typing import Any


def adf_to_markdown(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return str(value)
    return _block(value).strip()


def _inline(nodes: list[dict[str, Any]]) -> str:
    return "".join(_inline_node(n) for n in nodes or [])


def _inline_node(node: dict[str, Any]) -> str:
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    if kind == "text":
        text = node.get("text", "")
        for mark in node.get("marks") or []:
            mtype = mark.get("type")
            if mtype == "code":
                text = f"`{text}`"
            elif mtype == "strong":
                text = f"**{text}**"
            elif mtype == "em":
                text = f"*{text}*"
            elif mtype == "strike":
                text = f"~~{text}~~"
            elif mtype == "link":
                text = f"[{text}]({(mark.get('attrs') or {}).get('href', '')})"
        return text
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        return str(attrs.get("text") or "@user")
    if kind == "emoji":
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if kind in ("inlineCard", "blockCard", "embedCard"):
        return str(attrs.get("url") or "")
    if kind == "date":
        return str(attrs.get("timestamp") or "")
    if kind == "status":
        return f"[{attrs.get('text', '')}]"
    return _inline(node.get("content") or [])


def _block(node: dict[str, Any], depth: int = 0) -> str:
    kind = node.get("type")
    content = node.get("content") or []
    attrs = node.get("attrs") or {}

    if kind == "doc":
        return "\n\n".join(b for b in (_block(c, depth) for c in content) if b)
    if kind == "paragraph":
        return _inline(content)
    if kind == "heading":
        level = max(1, min(6, int(attrs.get("level", 1))))
        return f"{'#' * level} {_inline(content)}"
    if kind in ("bulletList", "orderedList"):
        lines = []
        for i, item in enumerate(content, start=1):
            marker = f"{i}." if kind == "orderedList" else "-"
            lines.append(_list_item(item, marker, depth))
        return "\n".join(lines)
    if kind == "taskList":
        return "\n".join(_task_item(item, depth) for item in content)
    if kind == "codeBlock":
        lang = attrs.get("language") or ""
        return f"```{lang}\n{_inline(content)}\n```"
    if kind == "blockquote":
        inner = "\n\n".join(_block(c, depth) for c in content)
        return "\n".join(f"> {line}" for line in inner.splitlines())
    if kind == "rule":
        return "---"
    if kind == "panel":
        inner = "\n\n".join(_block(c, depth) for c in content)
        return f"> **{str(attrs.get('panelType', 'info')).upper()}:** " + inner.replace("\n", "\n> ")
    if kind == "table":
        return _table(content)
    if kind in ("mediaSingle", "mediaGroup", "media"):
        return ""
    if kind == "text" or kind in ("hardBreak", "mention", "emoji", "inlineCard", "date", "status"):
        return _inline_node(node)
    # expand, nestedExpand, layoutSection, etc.: keep the title and the children.
    parts = [f"**{attrs['title']}**"] if attrs.get("title") else []
    parts += [b for b in (_block(c, depth) for c in content) if b]
    return "\n\n".join(parts)


def _list_item(item: dict[str, Any], marker: str, depth: int) -> str:
    indent = "  " * depth
    lines: list[str] = []
    for child in item.get("content") or []:
        if child.get("type") in ("bulletList", "orderedList"):
            lines.append(_block(child, depth + 1))
        else:
            text = _block(child, depth)
            prefix = f"{indent}{marker} " if not lines else f"{indent}  "
            lines.append(prefix + text.replace("\n", f"\n{indent}  "))
    return "\n".join(lines) if lines else f"{indent}{marker}"


def _task_item(item: dict[str, Any], depth: int) -> str:
    done = (item.get("attrs") or {}).get("state") == "DONE"
    return f"{'  ' * depth}- [{'x' if done else ' '}] {_inline(item.get('content') or [])}"


def _table(rows: list[dict[str, Any]]) -> str:
    rendered: list[list[str]] = []
    header_row = False
    for i, row in enumerate(rows):
        cells = row.get("content") or []
        if i == 0:
            header_row = all(c.get("type") == "tableHeader" for c in cells)
        rendered.append(
            [" ".join(_block(b) for b in (c.get("content") or [])).replace("|", "\\|").replace("\n", " ") for c in cells]
        )
    if not rendered:
        return ""
    width = max(len(r) for r in rendered)
    rendered = [r + [""] * (width - len(r)) for r in rendered]
    header = rendered[0] if header_row else [""] * width
    body = rendered[1:] if header_row else rendered
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)
