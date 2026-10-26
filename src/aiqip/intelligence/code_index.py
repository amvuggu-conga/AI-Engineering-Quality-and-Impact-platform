"""Code intelligence & architecture map for a development repository (ROC-CLM-API / ROC-CLM-UI)."""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..taxonomy import classify
from ..text import BM25Index, tokenize
from .csharp import classify_path, parse_file

INDEXED_EXT = (".cs", ".ts", ".tsx", ".js", ".jsx", ".json", ".csproj", ".props", ".targets", ".yml", ".yaml",
               ".config", ".sql", ".html")
SKIP_DIRS = {".git", "bin", "obj", "node_modules", "dist", "packages", ".vs", ".idea", "coverage", "TestResults",
             "wwwroot", ".angular", "out", "build"}
MAX_FILE_BYTES = 600_000


def iter_repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(INDEXED_EXT) and not fn.endswith((".min.js", ".lock.json", "package-lock.json")):
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size <= MAX_FILE_BYTES:
                        files.append(p)
                except OSError:
                    continue
    return files


def git_ownership(root: Path, max_commits: int = 3000) -> dict[str, list[list[Any]]]:
    """Map file -> [[author, commit_count, last_date], ...] from recent history."""
    if not (root / ".git").exists():
        return {}
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", f"-n{max_commits}", "--no-merges", "--name-only",
             "--format=@@%an|%ae|%as"],
            capture_output=True, text=True, timeout=300, check=True).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    last: dict[tuple[str, str], str] = {}
    author = ""
    date = ""
    for line in out.splitlines():
        if line.startswith("@@"):
            name, email, date = (line[2:].split("|") + ["", "", ""])[:3]
            author = f"{name} <{email}>" if email else name
            continue
        if line.strip() and author:
            counts[line.strip()][author] += 1
            last.setdefault((line.strip(), author), date)
    return {f: [[a, n, last.get((f, a), "")] for a, n in c.most_common(5)] for f, c in counts.items()}


def codeowners(root: Path) -> list[tuple[str, list[str]]]:
    for candidate in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        p = root / candidate
        if p.exists():
            rules = []
            for line in p.read_text(errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split()
                    rules.append((parts[0], parts[1:]))
            return rules
    return []


def build_code_index(repo_name: str, root: str | Path, kind: str = "api", with_git: bool = True) -> dict[str, Any]:
    root = Path(root)
    files: dict[str, Any] = {}
    bm25 = BM25Index()
    for p in iter_repo_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            source = p.read_text(errors="replace")
        except OSError:
            continue
        facts = parse_file(rel, source)
        category = classify_path(rel)
        type_names = [t["name"] for t in facts.types]
        descriptor = " ".join([rel.replace("/", " "), facts.namespace or "", " ".join(type_names),
                               " ".join(facts.methods), " ".join(e["route"] for e in facts.endpoints),
                               " ".join(facts.feature_flags), " ".join(facts.config_keys[:50])])
        areas = [a for a, _ in classify(descriptor, top_k=3)]
        files[rel] = {
            "category": category,
            "language": facts.language,
            "namespace": facts.namespace,
            "types": facts.types,
            "methods": facts.methods,
            "endpoints": facts.endpoints,
            "consumed_endpoints": facts.consumed_endpoints,
            "feature_flags": facts.feature_flags,
            "config_keys": facts.config_keys,
            "package_refs": facts.package_refs,
            "identifiers": facts.identifiers,
            "areas": areas,
        }
        # Weight structure (path, types, members, routes) above body text.
        tokens = tokenize(descriptor) * 3 + tokenize(source[:20000])
        bm25.add(rel, tokens)
    return {
        "repo": repo_name,
        "kind": kind,
        "root": str(root),
        "files": files,
        "bm25": bm25.to_dict(),
        "ownership": git_ownership(root) if with_git else {},
        "codeowners": codeowners(root),
    }


class CodeIndex:
    def __init__(self, data: dict[str, Any]):
        self.repo: str = data["repo"]
        self.kind: str = data.get("kind", "api")
        self.files: dict[str, Any] = data["files"]
        self.bm25 = BM25Index.from_dict(data.get("bm25", {}))
        self.ownership: dict[str, list[list[Any]]] = data.get("ownership", {})
        self.codeowners_rules: list[tuple[str, list[str]]] = [tuple(r) for r in data.get("codeowners", [])]
        self._type_to_files: dict[str, list[str]] = defaultdict(list)
        self._ident_to_files: dict[str, set[str]] = defaultdict(set)
        for path, info in self.files.items():
            for t in info.get("types", []):
                self._type_to_files[t["name"]].append(path)
            for ident in info.get("identifiers", []):
                self._ident_to_files[ident].add(path)

    @classmethod
    def load(cls, path: str | Path) -> "CodeIndex":
        return cls(json.loads(Path(path).read_text()))

    def file(self, path: str) -> dict[str, Any] | None:
        return self.files.get(path)

    def files_defining(self, type_name: str) -> list[str]:
        return self._type_to_files.get(type_name, [])

    def dependents(self, type_names: list[str], exclude: set[str] | None = None, limit: int = 50) -> dict[str, list[str]]:
        """Files referencing any of ``type_names`` (reverse dependency map)."""
        exclude = exclude or set()
        out: dict[str, list[str]] = {}
        for name in type_names:
            users = sorted(f for f in self._ident_to_files.get(name, set())
                           if f not in exclude and f not in self._type_to_files.get(name, []))
            if users:
                out[name] = users[:limit]
        return out

    def implementations(self, interface_name: str) -> list[str]:
        result = []
        for path, info in self.files.items():
            for t in info.get("types", []):
                bases = [b.strip().split("<")[0] for b in t.get("bases", "").split(",")]
                if interface_name in bases:
                    result.append(f"{t['name']} ({path})")
        return result

    def endpoints(self) -> list[dict[str, str]]:
        return [e for info in self.files.values() for e in info.get("endpoints", [])]

    def endpoints_for_types(self, type_names: set[str], files: set[str]) -> list[dict[str, str]]:
        hits = []
        for path, info in self.files.items():
            eps = info.get("endpoints", [])
            if not eps:
                continue
            idents = set(info.get("identifiers", []))
            if path in files or idents & type_names:
                hits.extend(eps)
        return hits

    def search(self, query: str | list[str], top_k: int = 15, categories: tuple[str, ...] | None = None) -> list[tuple[str, float]]:
        results = self.bm25.search(query, top_k=top_k * 4)
        if categories:
            results = [(p, s) for p, s in results if self.files.get(p, {}).get("category") in categories]
        return results[:top_k]

    def owners(self, path: str) -> list[tuple[str, int]]:
        owners = [(a, n) for a, n, *_ in self.ownership.get(path, [])]
        if owners:
            return owners
        matched: list[str] = []
        for pattern, users in self.codeowners_rules:
            pat = pattern.lstrip("/").rstrip("*")
            if pattern == "*" or path.startswith(pat) or (pat.startswith("*.") and path.endswith(pat[1:])):
                matched = users
        return [(u, 0) for u in matched]
