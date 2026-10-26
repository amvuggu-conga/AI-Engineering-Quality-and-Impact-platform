from aiqip.taxonomy import classify
from aiqip.text import BM25Index, adf_to_text, extract_jira_keys, tokenize


def test_tokenize_splits_identifiers_and_keeps_whole_word():
    tokens = tokenize("ContractCreatePreValidator handles generate_document")
    assert "contractcreateprevalidator" in tokens
    assert {"contract", "create", "validator"} <= set(tokens)
    assert "generate" in tokens and "document" in tokens


def test_extract_jira_keys_from_pr_body_link_format():
    body = "Pre and post validation\n\nFixes # https://conga.atlassian.net/browse/CONTRACTS-44346"
    assert extract_jira_keys("title", body) == ["CONTRACTS-44346"]


def test_extract_jira_keys_dedupes_filters_and_ignores_noise():
    keys = extract_jira_keys("CLM-1 fix", "see CLM-1 and CONTRACTS-2; encoding UTF-8", "branch/CONTRACTS-3-x")
    assert keys == ["CLM-1", "CONTRACTS-2", "CONTRACTS-3"]
    assert extract_jira_keys("CLM-1 CONTRACTS-2", projects=["CONTRACTS"]) == ["CONTRACTS-2"]


def test_bm25_ranks_relevant_document_first_and_roundtrips():
    idx = BM25Index()
    idx.add("a", "agreement renewal service renew term")
    idx.add("b", "clause library alternate clause")
    idx.add("c", "document generation template merge")
    assert idx.search("renew agreement")[0][0] == "a"
    again = BM25Index.from_dict(idx.to_dict())
    assert again.search("template generation")[0][0] == "c"


def test_adf_to_text_handles_lists_and_breaks():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}, {"type": "hardBreak"},
                                          {"type": "text", "text": "World"}]},
        {"type": "bulletList", "content": [{"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "step one"}]}]}]},
    ]}
    text = adf_to_text(doc)
    assert "Hello\nWorld" in text and "- step one" in text


def test_taxonomy_classifies_clm_language():
    assert classify("Pre and Post Validation For Contract Create and Generate Document Actions")[0][0] in {
        "validation-rules", "document-generation", "agreement-lifecycle"}
    top = {a for a, _ in classify("DocuSign envelope signer countersign", top_k=1)}
    assert top == {"esignature"}
