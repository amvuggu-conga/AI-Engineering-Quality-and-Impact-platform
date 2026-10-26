"""Conga CLM functional-area taxonomy.

This is the join key of the shared intelligence layer: code files, API routes, automation
tests, product documentation pages and historical defects are all classified into the
same functional areas, so "impacted code" can be translated into "impacted tests",
"relevant docs" and "related customer defects".

The keywords were derived from the CLM for Advantage Platform documentation structure
(documentation.conga.com) and CLM domain terminology. Teams can extend or override the
taxonomy through ``taxonomy`` in ``aiqip.yaml`` (see ``load_taxonomy``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from .text import tokenize


@dataclass(frozen=True)
class FunctionalArea:
    id: str
    name: str
    keywords: tuple[str, ...]
    risk: int = 1  # 1 (low) .. 3 (customer-critical)
    phrases: tuple[str, ...] = field(default_factory=tuple)


DEFAULT_AREAS: tuple[FunctionalArea, ...] = (
    FunctionalArea("agreement-lifecycle", "Agreement / Contract Lifecycle",
                   ("agreement", "contract", "lifecycle", "status", "statuscategory", "stage", "record", "request",
                    "create", "createcontract", "contractcreate", "draft", "intake"), 3,
                   ("contract create", "create agreement", "status category")),
    FunctionalArea("document-generation", "Document Generation & Authoring",
                   ("generate", "generation", "generatedocument", "docgen", "template", "merge", "document", "docx",
                    "pdf", "author", "authoring", "xauthor", "watermark", "attachment", "composer"), 3,
                   ("generate document", "document generation")),
    FunctionalArea("templates-clauses", "Templates & Clause Library",
                   ("template", "clause", "clauses", "playbook", "templatefilter", "filterrule", "library",
                    "fallback", "alternate"), 2),
    FunctionalArea("validation-rules", "Validation Rules & Callbacks",
                   ("validation", "validate", "validator", "prevalidation", "postvalidation", "precondition",
                    "callback", "rule", "rules", "constraint", "guard", "errormessage"), 3,
                   ("pre validation", "post validation")),
    FunctionalArea("approvals", "Approvals",
                   ("approval", "approve", "approver", "reject", "rejection", "approvalrequest", "escalation",
                    "submitforapproval"), 2),
    FunctionalArea("negotiation-review", "Negotiation, Review & Collaboration",
                   ("negotiate", "negotiation", "review", "reviewer", "redline", "collaborate", "collaboration",
                    "checkin", "checkout", "version", "versioning", "comparison", "compare"), 2),
    FunctionalArea("esignature", "eSignature (Conga Sign / DocuSign / Adobe Sign)",
                   ("signature", "esignature", "sign", "signer", "docusign", "adobesign", "envelope", "signatory",
                    "esign", "countersign"), 3),
    FunctionalArea("activation", "Activation & Fully Signed",
                   ("activate", "activation", "activated", "fullysigned", "inefect", "ineffect", "effective",
                    "publish", "executed"), 3),
    FunctionalArea("amend-renew-terminate", "Amend, Renew, Terminate & Expire",
                   ("amend", "amendment", "renew", "renewal", "terminate", "termination", "expire", "expiration",
                    "autorenew", "clone", "bulkamendment", "supersede", "extend"), 3),
    FunctionalArea("obligations", "Obligations & Milestones",
                   ("obligation", "milestone", "deliverable", "commitment", "compliance", "reminder"), 2),
    FunctionalArea("import-intelligence", "Import Offline & Contract Intelligence (AI extraction)",
                   ("import", "offline", "intelligentimport", "extraction", "extract", "discovery", "aime", "ai",
                    "ocr", "metadata", "classification", "contractintelligence"), 2),
    FunctionalArea("search-reporting", "Search, Views, Reports & Dashboards",
                   ("search", "smartsearch", "index", "filter", "view", "listview", "report", "dashboard", "query",
                    "export", "ineffectview"), 1),
    FunctionalArea("security-permissions", "Security, Roles & Permissions",
                   ("permission", "role", "roles", "profile", "security", "access", "authorization", "authorize",
                    "sharing", "visibility", "tenant", "user", "group", "permissiongroup", "auth", "token", "oauth"), 3),
    FunctionalArea("admin-configuration", "Administration, Settings & Feature Flags",
                   ("admin", "administration", "setting", "settings", "configuration", "config", "implementationtask",
                    "featureflag", "feature", "flag", "toggle", "setup", "picklist", "customfield", "metadata"), 2),
    FunctionalArea("notifications", "Notifications & Email",
                   ("notification", "notify", "email", "mail", "alert", "emailtemplate", "subscription"), 1),
    FunctionalArea("workflow-orchestration", "Workflows, Flows & Async Jobs",
                   ("workflow", "flow", "orchestrate", "orchestration", "job", "queue", "event", "eventbus",
                    "trigger", "scheduler", "background", "async", "worker", "message", "handler"), 2),
    FunctionalArea("integrations", "Integrations (CRM, Salesforce, Composer, X-Author, APIs)",
                   ("integration", "salesforce", "crm", "opportunity", "account", "connector", "webhook", "sync",
                    "external", "api", "client", "sdk", "xauthor"), 2),
    FunctionalArea("related-agreements", "Parent / Child & Related Agreements",
                   ("parent", "child", "related", "relationship", "hierarchy", "familytree", "masteragreement"), 2),
    FunctionalArea("data-persistence", "Data Model & Persistence",
                   ("repository", "entity", "dbcontext", "migration", "schema", "database", "sql", "persistence",
                    "dto", "model", "mapper", "mapping", "cache", "redis"), 2),
)


@lru_cache(maxsize=None)
def _area_terms(area: FunctionalArea) -> frozenset[str]:
    terms: set[str] = set()
    for kw in area.keywords + area.phrases:
        terms.update(tokenize(kw, keep_stopwords=True))
    return frozenset(terms)


def classify(text: str | Iterable[str], areas: tuple[FunctionalArea, ...] = DEFAULT_AREAS,
             top_k: int = 3, min_hits: int = 1) -> list[tuple[str, float]]:
    """Return ``(area_id, score)`` sorted by score for free text or a token list."""
    tokens = tokenize(text, keep_stopwords=True) if isinstance(text, str) else list(text)
    if not tokens:
        return []
    token_set = set(tokens)
    lowered = text.lower() if isinstance(text, str) else " ".join(tokens)
    results: list[tuple[str, float]] = []
    for area in areas:
        terms = _area_terms(area)
        hits = token_set & terms
        if len(hits) < min_hits:
            continue
        freq = sum(1 for t in tokens if t in terms)
        phrase_bonus = sum(2.0 for p in area.phrases if p in lowered)
        score = len(hits) * 1.5 + min(freq, 20) * 0.25 + phrase_bonus
        results.append((area.id, round(score, 2)))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def area_by_id(area_id: str, areas: tuple[FunctionalArea, ...] = DEFAULT_AREAS) -> FunctionalArea | None:
    return next((a for a in areas if a.id == area_id), None)


def area_name(area_id: str) -> str:
    area = area_by_id(area_id)
    return area.name if area else area_id


def load_taxonomy(extra: list[dict] | None) -> tuple[FunctionalArea, ...]:
    if not extra:
        return DEFAULT_AREAS
    areas = {a.id: a for a in DEFAULT_AREAS}
    for item in extra:
        areas[item["id"]] = FunctionalArea(item["id"], item.get("name", item["id"]),
                                           tuple(item.get("keywords", [])), int(item.get("risk", 1)),
                                           tuple(item.get("phrases", [])))
    return tuple(areas.values())
