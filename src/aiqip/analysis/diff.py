"""Unified-diff parsing and changed-member detection (C# and TypeScript)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..intelligence.csharp import CS_KEYWORDS, INTERFACE_METHOD_RE, METHOD_RE, TS_CLASS_RE, TS_METHOD_RE, TYPE_RE
from ..models import ChangedMember

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


@dataclass
class Hunk:
    old_start: int
    new_start: int
    context: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    lines: list[tuple[str, str]] = field(default_factory=list)  # (" " | "+" | "-", text) in order


def parse_patch(patch: str | None) -> list[Hunk]:
    hunks: list[Hunk] = []
    if not patch:
        return hunks
    current: Hunk | None = None
    for line in patch.splitlines():
        m = HUNK_RE.match(line)
        if m:
            current = Hunk(int(m.group(1)), int(m.group(3)), m.group(5).strip())
            hunks.append(current)
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current.added.append(line[1:])
            current.lines.append(("+", line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            current.removed.append(line[1:])
            current.lines.append(("-", line[1:]))
        elif line.startswith(" ") or line == "":
            current.lines.append((" ", line[1:]))
    return hunks


def split_unified_diff(diff: str) -> dict[str, str]:
    """Split a full ``git diff`` into ``{path: patch}``."""
    out: dict[str, list[str]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            path = m.group(2) if m else None
            if path:
                out[path] = []
            continue
        if path and not line.startswith(("index ", "--- ", "+++ ", "new file mode", "deleted file mode",
                                         "similarity index", "rename from", "rename to")):
            out[path].append(line)
    return {p: "\n".join(lines) for p, lines in out.items()}


def changed_members(path: str, patch: str | None) -> list[ChangedMember]:
    lower = path.lower()
    is_cs = lower.endswith(".cs")
    is_ts = lower.endswith((".ts", ".tsx", ".js", ".jsx"))
    if not (is_cs or is_ts):
        return []
    members: dict[tuple[str, str, str], ChangedMember] = {}
    current_type: str | None = None
    current_kind: str | None = None

    def add(kind: str, name: str, container: str | None) -> None:
        if name in CS_KEYWORDS or (kind == "method" and name == container):
            return
        members.setdefault((kind, name, container or ""), ChangedMember(kind, name, path, container))

    ts_skip = {"if", "for", "while", "switch", "catch", "function"}
    for hunk in parse_patch(patch):
        current_method: str | None = None
        ctx = hunk.context
        if is_cs and ctx:
            tm = TYPE_RE.match(ctx)
            mm = METHOD_RE.match(ctx)
            if tm:
                current_type, current_kind = tm.group(2), tm.group(1)
            elif mm:
                current_method = mm.group(1)
        for op, line in hunk.lines:
            changed = op != " "
            if is_cs:
                tm = TYPE_RE.match(line)
                mm = None if tm else METHOD_RE.match(line)
                im = None
                if not tm and not mm and current_kind == "interface" and line.strip() and \
                        line.split()[0] not in CS_KEYWORDS:
                    im = INTERFACE_METHOD_RE.match(line)
            else:
                tm = TS_CLASS_RE.search(line)
                mm = None if tm else TS_METHOD_RE.match(line)
                if mm and mm.group(1) in ts_skip:
                    mm = None
                im = None
            if tm:
                current_type, current_kind, current_method = tm.group(2), tm.group(1), None
                if changed:
                    add(tm.group(1), tm.group(2), None)
            elif mm or im:
                current_method = (mm or im).group(1)
                if changed:
                    add("method", current_method, current_type)
            elif changed and line.strip() and current_method:
                add("method", current_method, current_type)
    stem = path.rsplit("/", 1)[-1].split(".")[0]
    for m in members.values():
        if m.container is None and m.kind == "method":
            m.container = stem
    return [m for m in members.values() if not (m.kind == "method" and m.name == m.container)]
