from aiqip.intelligence.knowledge import BUNDLED_INDEX, KnowledgeBase, build_docs_index


def test_bundled_clm_docs_index_is_real_content_and_searchable():
    kb = KnowledgeBase.load(None)
    assert BUNDLED_INDEX.exists() and len(kb) > 1000
    assert all(d["has_content"] for d in kb.docs.values())
    hits = kb.search("send contract for electronic signature docusign", top_k=5)
    assert any("signature" in h.title.lower() for h in hits)
    titles = [h.title.lower() for h in hits]
    assert len(titles) == len(set(titles))
    assert all(h.url.startswith("https://documentation.conga.com/en/clm-for-advantage-platform/") for h in hits)


def test_build_docs_index_ignores_failed_pages():
    data = build_docs_index([
        {"url": "u1", "title": "Renewing an Agreement", "section": "Users", "text": "renew the agreement term"},
        {"url": "u2", "title": "Broken", "section": "", "text": "shell", "error": "no article"},
    ], "test")
    kb = KnowledgeBase(data)
    assert kb.docs["u2"]["has_content"] is False
    assert kb.search("renew agreement")[0].url == "u1"
