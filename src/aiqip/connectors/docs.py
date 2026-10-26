"""Conga product documentation connector (documentation.conga.com, Heretto portal).

The portal publishes per-product sitemaps and serves server-rendered HTML to crawlers that
identify as bots, so pages can be indexed without a browser.
"""

from __future__ import annotations

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx

USER_AGENT = "aiqip-indexer-bot/0.1 (+https://github.com/amvuggu-conga/AI-Engineering-Quality-and-Impact-platform)"


def slug_to_title(slug: str) -> str:
    words = slug.replace("_", "-").split("-")
    small = {"and", "or", "of", "the", "for", "to", "in", "on", "a", "an", "with", "by"}
    out = []
    for i, w in enumerate(words):
        if not w:
            continue
        if w.lower() in {"clm", "api", "ai", "pdf", "sso", "crm", "url", "id", "json", "xml"}:
            out.append(w.upper())
        elif i > 0 and w in small:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def page_from_url(url: str) -> dict[str, Any]:
    parts = [p for p in urlparse(url).path.split("/") if p]
    # /en/<product>/<version>/<section>/.../<slug>
    product = parts[1] if len(parts) > 1 else ""
    sections = parts[3:-1] if len(parts) > 4 else []
    slug = parts[-1] if parts else ""
    return {
        "url": url,
        "product": product,
        "title": slug_to_title(slug),
        "section": " > ".join(slug_to_title(s) for s in sections),
        "summary": "",
    }


def extract_article_text(page_html: str) -> tuple[str | None, str]:
    title_m = re.search(r"<title>(.*?)</title>", page_html, re.S)
    title = html.unescape(title_m.group(1)).split("|")[0].strip() if title_m else None
    m = re.search(r"<article[^>]*>(.*?)</article>", page_html, re.S)
    body = m.group(1) if m else page_html
    body = re.sub(r"<(script|style|nav)[^>]*>.*?</\1>", " ", body, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", html.unescape(body)).strip()
    return title, body


class DocsClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = 30.0):
        self.http = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout,
                                 follow_redirects=True, transport=transport)

    def sitemap_urls(self, sitemap_url: str) -> list[str]:
        resp = self.http.get(sitemap_url)
        resp.raise_for_status()
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text)
        if "<sitemapindex" in resp.text:
            urls: list[str] = []
            for child in locs:
                urls.extend(self.sitemap_urls(child))
            return urls
        return locs

    def fetch_page(self, url: str, retries: int = 4) -> dict[str, Any]:
        """Fetch one page. The portal intermittently serves its client-side shell instead of the
        rendered article; that response is detected and retried rather than indexed."""
        page = page_from_url(url)
        for attempt in range(retries):
            try:
                resp = self.http.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                page["error"] = str(exc)
                time.sleep(1.5 * (attempt + 1))
                continue
            if "<article" not in resp.text or "unsupported browser" in resp.text[:20000]:
                page["error"] = "portal returned client-side shell (no rendered article)"
                time.sleep(1.5 * (attempt + 1))
                continue
            title, text = extract_article_text(resp.text)
            if title:
                page["title"] = title
            page["text"] = text
            page.pop("error", None)
            break
        return page

    def crawl(self, sitemaps: list[str], fetch_content: bool = False, max_pages: int = 400,
              workers: int = 2, delay_s: float = 0.5) -> list[dict[str, Any]]:
        urls: list[str] = []
        for sm in sitemaps:
            urls.extend(u for u in self.sitemap_urls(sm) if u not in urls)
        if not fetch_content:
            return [page_from_url(u) for u in urls]

        def fetch(u: str) -> dict[str, Any]:
            time.sleep(delay_s)
            return self.fetch_page(u)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            pages = list(pool.map(fetch, urls[:max_pages]))
        pages.extend(page_from_url(u) for u in urls[max_pages:])
        return pages
