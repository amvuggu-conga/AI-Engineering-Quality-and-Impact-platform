"""Lightweight, regex-based structural extraction for C#, TypeScript and config files.

This intentionally avoids a full compiler front-end (Roslyn) so it runs anywhere in CI
without a .NET SDK; it extracts what impact analysis needs: namespaces, types, members,
ASP.NET routes, feature flags, configuration keys and referenced identifiers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

CS_KEYWORDS = {
    "if", "for", "foreach", "while", "switch", "catch", "using", "lock", "return", "new", "throw", "nameof",
    "typeof", "sizeof", "default", "when", "where", "base", "this", "await", "yield", "else", "do", "try",
    "get", "set", "init", "fixed", "checked", "unchecked",
}
HTTP_ATTRS = {"HttpGet": "GET", "HttpPost": "POST", "HttpPut": "PUT", "HttpDelete": "DELETE",
              "HttpPatch": "PATCH", "HttpHead": "HEAD", "HttpOptions": "OPTIONS"}

NAMESPACE_RE = re.compile(r"^\s*namespace\s+([\w.]+)", re.M)
TYPE_RE = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|internal|private|protected|static|sealed|abstract|partial|readonly|unsafe|new|file)\s+)*"
    r"(class|interface|record|struct|enum)\s+(?:class\s+|struct\s+)?([A-Z_]\w*)(?:<[^>{]*>)?(?:\s*\([^)]*\))?\s*(?::\s*([^{\n]+))?",
    re.M,
)
METHOD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|abstract|async|sealed|extern|new|partial|unsafe)\s+)+"
    r"(?:[\w<>\[\],.?()\s]+?\s+)?([A-Z_]\w*)\s*(?:<[^>()]*>)?\s*\(",
    re.M,
)
INTERFACE_METHOD_RE = re.compile(r"^\s*(?:Task<[^;]+>|Task|[\w<>\[\],.?]+)\s+([A-Z_]\w*)\s*(?:<[^>()]*>)?\s*\([^;{]*\)\s*;", re.M)
PROPERTY_RE = re.compile(r"^\s*public\s+(?:virtual\s+|override\s+|static\s+|required\s+)*[\w<>\[\],.?]+\s+([A-Z]\w*)\s*\{\s*get", re.M)
ATTR_RE = re.compile(r"\[\s*(Route|HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch|HttpHead|HttpOptions)\s*(?:\(\s*(?:template\s*:\s*)?@?\"([^\"]*)\"[^)]*\))?\s*\]")
MINIMAL_API_RE = re.compile(r"\.Map(Get|Post|Put|Delete|Patch)\s*\(\s*@?\"([^\"]+)\"")
FLAG_CALL_RE = re.compile(
    r"\b\w*(?:Feature|Flag|Toggle)\w*\s*(?:<[^>]*>)?\s*\(\s*(?:nameof\(\s*)?(?:@?\"([A-Za-z][\w.:\-]+)\"|([A-Z][\w.]+))")
FLAG_CONST_RE = re.compile(r"(?:const|static\s+readonly)\s+string\s+(\w*(?:Feature|Flag|Toggle)\w*)\s*=\s*\"([^\"]+)\"")
CONFIG_KEY_RE = re.compile(
    r"(?:Configuration|_config\w*|config\w*)\s*\[\s*\"([^\"]+)\"\s*\]|GetSection\(\s*\"([^\"]+)\"|GetValue<[^>]+>\(\s*\"([^\"]+)\"|IOptions(?:Snapshot|Monitor)?<(\w+)>")
IDENT_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\b")
STRING_ROUTE_RE = re.compile(r"[\"'`](/?(?:api|clm|v\d)[/\w{}\-.:$]*?)[\"'`]")
TS_CLASS_RE = re.compile(r"export\s+(?:default\s+)?(?:abstract\s+)?(class|interface|enum|function|const)\s+([A-Za-z_]\w*)")
TS_METHOD_RE = re.compile(r"^\s*(?:public|private|protected|async|static|\s)*([a-zA-Z_]\w*)\s*\([^)]*\)\s*(?::\s*[^{=]+)?\{", re.M)
TS_HTTP_RE = re.compile(r"\.(get|post|put|delete|patch)\s*(?:<[^>]*>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
CSPROJ_REF_RE = re.compile(r"<(PackageReference|ProjectReference)\s+Include=\"([^\"]+)\"")


@dataclass
class FileFacts:
    path: str
    language: str
    namespace: str | None = None
    types: list[dict[str, str]] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    endpoints: list[dict[str, str]] = field(default_factory=list)
    consumed_endpoints: list[str] = field(default_factory=list)
    feature_flags: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    package_refs: list[str] = field(default_factory=list)


def _norm_route(*parts: str) -> str:
    joined = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return "/" + joined if joined else "/"


def parse_csharp(path: str, source: str) -> FileFacts:
    facts = FileFacts(path=path, language="csharp")
    m = NAMESPACE_RE.search(source)
    facts.namespace = m.group(1) if m else None

    for tm in TYPE_RE.finditer(source):
        kind, name, bases = tm.group(1), tm.group(2), (tm.group(3) or "").strip()
        facts.types.append({"kind": kind, "name": name, "bases": re.sub(r"\s+", " ", bases)[:200]})

    names = set()
    for mm in METHOD_RE.finditer(source):
        name = mm.group(1)
        if name in CS_KEYWORDS or any(t["name"] == name for t in facts.types):
            continue
        names.add(name)
    if any(t["kind"] == "interface" for t in facts.types):
        names.update(n for n in INTERFACE_METHOD_RE.findall(source) if n not in CS_KEYWORDS)
    facts.methods = sorted(names)
    facts.properties = sorted(set(PROPERTY_RE.findall(source)))[:200]
    facts.endpoints = _csharp_endpoints(path, source, facts)

    flags = {a or b for a, b in FLAG_CALL_RE.findall(source)}
    flags.update(v for _, v in FLAG_CONST_RE.findall(source))
    facts.feature_flags = sorted(f for f in flags if f and len(f) > 2 and not f.startswith(("System.", "Task")))[:100]
    keys: set[str] = set()
    for groups in CONFIG_KEY_RE.findall(source):
        keys.update(g for g in groups if g)
    facts.config_keys = sorted(keys)[:100]
    facts.identifiers = sorted(set(IDENT_RE.findall(source)))[:2000]
    return facts


def _csharp_endpoints(path: str, source: str, facts: FileFacts) -> list[dict[str, str]]:
    controller = next((t["name"] for t in facts.types if t["kind"] == "class"), "")
    is_controller = controller.endswith("Controller") or "ControllerBase" in source or "[ApiController]" in source
    endpoints: list[dict[str, str]] = []
    for mm in MINIMAL_API_RE.finditer(source):
        endpoints.append({"method": mm.group(1).upper(), "route": _norm_route(mm.group(2)), "controller": controller,
                          "action": "", "file": path})
    if not is_controller:
        return endpoints

    ctrl_token = controller[: -len("Controller")] if controller.endswith("Controller") else controller
    class_pos = source.find(f"class {controller}") if controller else -1
    class_route = ""
    for am in ATTR_RE.finditer(source[: class_pos if class_pos > 0 else 0]):
        if am.group(1) == "Route":
            class_route = am.group(2) or ""

    pending: list[tuple[str, str]] = []
    body = source[class_pos:] if class_pos > 0 else source
    for line in body.splitlines():
        for am in ATTR_RE.finditer(line):
            pending.append((am.group(1), am.group(2) or ""))
        mm = METHOD_RE.match(line)
        if mm and pending:
            action = mm.group(1)
            verbs = [(HTTP_ATTRS[a], t) for a, t in pending if a in HTTP_ATTRS]
            route_attr = next((t for a, t in pending if a == "Route"), "")
            for verb, tmpl in verbs or [("ANY", route_attr)]:
                tmpl = tmpl or route_attr
                route = tmpl if tmpl.startswith("/") or tmpl.startswith("~") else _norm_route(class_route, tmpl)
                route = route.lstrip("~").replace("[controller]", ctrl_token).replace("[action]", action)
                endpoints.append({"method": verb, "route": _norm_route(route), "controller": controller,
                                  "action": action, "file": path})
            pending = []
        elif pending and line.strip().endswith(";"):
            pending = []
    return endpoints


def parse_typescript(path: str, source: str) -> FileFacts:
    facts = FileFacts(path=path, language="typescript")
    for kind, name in TS_CLASS_RE.findall(source):
        facts.types.append({"kind": kind, "name": name, "bases": ""})
    facts.methods = sorted({m for m in TS_METHOD_RE.findall(source)
                            if m not in {"if", "for", "while", "switch", "catch", "function", "constructor"}})[:300]
    consumed = {u for _, u in TS_HTTP_RE.findall(source)}
    consumed.update(STRING_ROUTE_RE.findall(source))
    facts.consumed_endpoints = sorted(c for c in consumed if "/" in c)[:100]
    flags = {a or b for a, b in FLAG_CALL_RE.findall(source)}
    facts.feature_flags = sorted(f for f in flags if f)[:50]
    facts.identifiers = sorted(set(IDENT_RE.findall(source)))[:1500]
    return facts


def parse_json_config(path: str, source: str) -> FileFacts:
    facts = FileFacts(path=path, language="json")
    try:
        data = json.loads(re.sub(r"^\s*//.*$", "", source, flags=re.M))
    except json.JSONDecodeError:
        return facts
    keys: list[str] = []

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                full = f"{prefix}:{k}" if prefix else k
                keys.append(full)
                if re.search(r"feature|flag|toggle", k, re.I) and isinstance(v, dict):
                    facts.feature_flags.extend(f"{full}:{fk}" for fk in v.keys())
                if len(keys) < 500:
                    walk(v, full)

    walk(data, "")
    facts.config_keys = keys[:300]
    return facts


def parse_csproj(path: str, source: str) -> FileFacts:
    facts = FileFacts(path=path, language="msbuild")
    facts.package_refs = sorted({f"{kind}:{name}" for kind, name in CSPROJ_REF_RE.findall(source)})
    return facts


def parse_file(path: str, source: str) -> FileFacts:
    lower = path.lower()
    if lower.endswith(".cs"):
        return parse_csharp(path, source)
    if lower.endswith((".ts", ".tsx", ".js", ".jsx")):
        return parse_typescript(path, source)
    if lower.endswith(".json"):
        return parse_json_config(path, source)
    if lower.endswith((".csproj", ".props", ".targets")):
        return parse_csproj(path, source)
    return FileFacts(path=path, language="other", identifiers=sorted(set(IDENT_RE.findall(source)))[:500])


def classify_path(path: str) -> str:
    p = path.replace("\\", "/")
    lower = p.lower()
    name = lower.rsplit("/", 1)[-1]
    if re.search(r"(^|/)(tests?|unittests?|integrationtests?|specs?)(/|$)|\.tests?(/|\.)|tests?\.cs$|\.spec\.[tj]sx?$|\.test\.[tj]sx?$", lower):
        return "test"
    if "/migrations/" in lower or name.endswith(".sql"):
        return "migration"
    if lower.startswith(".github/") or name in ("dockerfile", "azure-pipelines.yml", "jenkinsfile", "makefile") or \
            name.endswith((".csproj", ".sln", ".props", ".targets", "package.json", "package-lock.json", "nuget.config")):
        return "build"
    if name.startswith("appsettings") or name.endswith((".config", ".yaml", ".yml", ".env", ".ini", ".toml")) or \
            name in ("launchsettings.json",) or "/config/" in lower or "/helm/" in lower:
        return "config"
    if name.endswith((".md", ".txt", ".rst")):
        return "docs"
    if name.endswith((".html", ".scss", ".css", ".tsx", ".jsx")) or (name.endswith(".ts") and "/app/" in lower):
        return "ui"
    if name.endswith((".cs", ".ts", ".js", ".py", ".java", ".go")):
        return "code"
    if name.endswith(".json"):
        return "config"
    return "other"
