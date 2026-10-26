"""Minimal Atlassian Document Format builder for Jira Cloud comments."""

from __future__ import annotations

from typing import Any, Union

Inline = Union[str, tuple[str, str], dict[str, Any]]  # plain text | (text, url) | ("**bold**" via dict)


def text(value: str, bold: bool = False, code: bool = False, url: str | None = None) -> dict[str, Any]:
    marks = []
    if bold:
        marks.append({"type": "strong"})
    if code:
        marks.append({"type": "code"})
    if url:
        marks.append({"type": "link", "attrs": {"href": url}})
    node: dict[str, Any] = {"type": "text", "text": value or " "}
    if marks:
        node["marks"] = marks
    return node


def _inline(items: list[Inline] | Inline) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        items = [items]
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(text(item))
        elif isinstance(item, tuple):
            out.append(text(item[0], url=item[1]))
        else:
            out.append(item)
    return out


class ADFDocument:
    def __init__(self) -> None:
        self.content: list[dict[str, Any]] = []

    def heading(self, value: str, level: int = 3) -> "ADFDocument":
        self.content.append({"type": "heading", "attrs": {"level": level}, "content": [text(value)]})
        return self

    def paragraph(self, *items: Inline) -> "ADFDocument":
        self.content.append({"type": "paragraph", "content": _inline(list(items))})
        return self

    def bullets(self, items: list[list[Inline] | Inline]) -> "ADFDocument":
        if not items:
            return self
        self.content.append({"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": _inline(i)}]} for i in items]})
        return self

    def panel(self, panel_type: str, *items: Inline) -> "ADFDocument":
        self.content.append({"type": "panel", "attrs": {"panelType": panel_type},
                             "content": [{"type": "paragraph", "content": _inline(list(items))}]})
        return self

    def rule(self) -> "ADFDocument":
        self.content.append({"type": "rule"})
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"type": "doc", "version": 1, "content": self.content}


def adf_to_markdown(doc: dict[str, Any]) -> str:
    """Render the ADF we generate as markdown for dry-run previews."""
    lines: list[str] = []

    def inline(nodes: list[dict[str, Any]]) -> str:
        parts = []
        for n in nodes:
            t = n.get("text", "")
            marks = {m["type"]: m for m in n.get("marks", [])}
            trailing = " " if t.endswith(" ") and marks else ""
            t = t.rstrip() if trailing else t
            if "code" in marks:
                t = f"`{t}`"
            if "strong" in marks:
                t = f"**{t}**"
            t += trailing
            if "link" in marks:
                t = f"[{t}]({marks['link']['attrs']['href']})"
            parts.append(t)
        return "".join(parts)

    for block in doc.get("content", []):
        bt = block["type"]
        if bt == "heading":
            lines.append("#" * block["attrs"]["level"] + " " + inline(block["content"]))
        elif bt == "paragraph":
            lines.append(inline(block["content"]))
        elif bt == "panel":
            lines.append(f"> [{block['attrs']['panelType'].upper()}] " + inline(block["content"][0]["content"]))
        elif bt == "bulletList":
            for li in block["content"]:
                lines.append("- " + inline(li["content"][0]["content"]))
        elif bt == "rule":
            lines.append("---")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
