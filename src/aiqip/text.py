"""Text utilities: identifier-aware tokenization, a dependency-free BM25 index,
Jira ADF conversion and Jira-key extraction."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is", "it",
    "its", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with", "when", "not",
    "but", "if", "then", "else", "can", "should", "would", "could", "we", "i", "you", "they", "our",
    "after", "before", "into", "than", "so", "do", "does", "did", "any", "all", "also", "there", "which",
    "using", "use", "used", "new", "get", "set", "var", "void", "public", "private", "protected",
    "internal", "static", "async", "await", "return", "class", "namespace", "string", "int", "bool",
    "task", "null", "true", "false", "const", "readonly", "override", "virtual", "this", "base",
    "system", "linq", "collections", "generic", "threading", "tasks", "summary", "param", "returns",
    "cs", "json", "src", "test", "tests", "http", "https", "www", "com", "net", "issue", "please",
    "able", "unable", "able", "steps", "step", "expected", "actual", "result", "results", "customer",
}

JIRA_KEY_RE = re.compile(r"(?<![A-Z0-9])([A-Z][A-Z0-9]{1,15}-\d{1,7})(?![0-9])")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def split_identifier(word: str) -> list[str]:
    return [p.lower() for p in _CAMEL_RE.findall(word)]


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    """Split prose and code identifiers into lowercase terms.

    ``ContractCreateValidator`` yields ``contractcreatevalidator`` plus ``contract``,
    ``create`` and ``validator`` so that code and natural language meet in the same space.
    """
    if not text:
        return []
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text):
        parts = [p for p in re.split(r"_+", raw) if p]
        sub: list[str] = []
        for p in parts:
            sub.extend(split_identifier(p))
        whole = raw.lower().replace("_", "")
        candidates = [whole] + (sub if len(sub) > 1 else [])
        for t in candidates:
            if len(t) < 2:
                continue
            if not keep_stopwords and t in STOPWORDS:
                continue
            tokens.append(stem(t))
    return tokens


def stem(token: str) -> str:
    """Very light suffix stripping so 'agreements'/'agreement' and 'validation'/'validate' meet."""
    for suffix, repl in (("ations", "ate"), ("ation", "ate"), ("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)] + repl
    return token


def extract_jira_keys(*texts: str | None, projects: Iterable[str] | None = None) -> list[str]:
    allowed = {p.upper() for p in projects} if projects else None
    seen: list[str] = []
    for text in texts:
        if not text:
            continue
        for key in JIRA_KEY_RE.findall(text):
            if key.startswith(("UTF-", "SHA-", "ISO-", "HTTP-", "TLS-", "RFC-", "CVE-")):
                continue
            if allowed and key.split("-")[0] not in allowed:
                continue
            if key not in seen:
                seen.append(key)
    return seen


class BM25Index:
    """Small in-memory BM25 index. Documents are (id, text) pairs; serializable to JSON."""

    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_tf: list[dict[str, int]] = []
        self.doc_len: list[int] = []
        self.df: Counter[str] = Counter()

    def add(self, doc_id: str, text: str | list[str]) -> None:
        tokens = text if isinstance(text, list) else tokenize(text)
        tf = Counter(tokens)
        self.doc_ids.append(doc_id)
        self.doc_tf.append(dict(tf))
        self.doc_len.append(len(tokens))
        self.df.update(tf.keys())

    def __len__(self) -> int:
        return len(self.doc_ids)

    def search(self, query: str | list[str], top_k: int = 10, min_score: float = 0.0) -> list[tuple[str, float]]:
        if not self.doc_ids:
            return []
        q_tokens = query if isinstance(query, list) else tokenize(query)
        q = Counter(q_tokens)
        n = len(self.doc_ids)
        avgdl = (sum(self.doc_len) / n) or 1.0
        scores: list[tuple[str, float]] = []
        idf = {t: math.log(1 + (n - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5)) for t in q}
        for i, tf in enumerate(self.doc_tf):
            s = 0.0
            dl = self.doc_len[i] or 1
            for t, qf in q.items():
                f = tf.get(t)
                if not f:
                    continue
                s += idf[t] * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / avgdl))
            if s > min_score:
                scores.append((self.doc_ids[i], s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def to_dict(self) -> dict[str, Any]:
        return {"ids": self.doc_ids, "tf": self.doc_tf, "len": self.doc_len}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BM25Index":
        idx = cls()
        idx.doc_ids = list(data.get("ids", []))
        idx.doc_tf = [dict(d) for d in data.get("tf", [])]
        idx.doc_len = list(data.get("len", []))
        for tf in idx.doc_tf:
            idx.df.update(tf.keys())
        return idx


def adf_to_text(node: Any) -> str:
    """Convert Atlassian Document Format (Jira Cloud v3) to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    ntype = node.get("type")
    if ntype == "text":
        return node.get("text", "")
    if ntype == "hardBreak":
        return "\n"
    if ntype in ("mention",):
        return node.get("attrs", {}).get("text", "")
    if ntype in ("inlineCard", "blockCard"):
        return node.get("attrs", {}).get("url", "")
    inner = adf_to_text(node.get("content", []))
    if ntype == "listItem":
        return "- " + inner.strip() + "\n"
    if ntype in ("paragraph", "heading", "codeBlock", "blockquote", "rule", "panel", "tableRow"):
        return inner + "\n"
    if ntype in ("tableCell", "tableHeader"):
        return inner.strip() + " | "
    return inner


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
