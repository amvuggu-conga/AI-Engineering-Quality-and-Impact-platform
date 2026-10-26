from pathlib import Path

from aiqip.intelligence.test_index import TestIndex, build_test_index, discover_tests


def test_discover_java_testng_with_groups():
    src = '''package com.conga.clm;
import org.testng.annotations.Test;
public class ContractCreateTests {
    @Test(groups = {"regression", "contract"}, description = "create contract with prevalidation")
    public void createContractRunsPreValidation() { post("/api/clm/v1/contracts", body); }
}'''
    tests = discover_tests("src/test/java/com/conga/clm/ContractCreateTests.java", src)
    assert tests[0]["id"] == "com.conga.clm.ContractCreateTests#createContractRunsPreValidation"
    assert tests[0]["tags"] == ["regression", "contract"]
    assert tests[0]["framework"] == "testng"


def test_discover_csharp_nunit_with_categories():
    src = '''namespace Clm.Automation.Api
{
    [TestFixture, Category("Agreements")]
    public class GenerateDocumentTests
    {
        [Test, Category("Smoke")]
        public async Task GenerateDocument_ReturnsPdf() { }

        [TestCase("a")]
        public void Generate_WithTemplate(string t) { }
    }
}'''
    tests = discover_tests("Api/GenerateDocumentTests.cs", src)
    ids = [t["id"] for t in tests]
    assert ids == ["Clm.Automation.Api.GenerateDocumentTests.GenerateDocument_ReturnsPdf",
                   "Clm.Automation.Api.GenerateDocumentTests.Generate_WithTemplate"]
    assert "Smoke" in tests[0]["tags"] and "Agreements" in tests[0]["tags"]
    assert tests[0]["framework"] == "nunit"


def test_discover_playwright_and_pytest_and_gherkin():
    ts = "import { test } from '@playwright/test';\ntest.describe('Agreements @regression', () => {\n  test('renew agreement @smoke', async () => {});\n});"
    t = discover_tests("e2e/agreements.spec.ts", ts)
    assert t[0]["framework"] == "playwright" and "smoke" in t[0]["tags"] and "regression" in t[0]["tags"]
    py = "import pytest\n\n@pytest.mark.smoke\ndef test_activate_agreement():\n    pass\n"
    p = discover_tests("tests/test_activate.py", py)
    assert p[0]["id"] == "tests/test_activate.py::test_activate_agreement" and p[0]["tags"] == ["smoke"]
    feature = "@clm\nFeature: Sign\n\n  @smoke\n  Scenario: Send for eSignature\n    Given x\n"
    g = discover_tests("features/sign.feature", feature)
    assert g[0]["id"] == "features/sign.feature:5" and set(g[0]["tags"]) == {"clm", "smoke"}


def test_build_index_with_mapping_rules(tmp_path: Path):
    (tmp_path / "ApiTests.java").write_text(
        'package p;\nimport org.testng.annotations.Test;\npublic class ApiTests {\n'
        '  @Test(groups = {"x"})\n  public void misc() { }\n}')
    (tmp_path / "aiqip-test-map.yaml").write_text(
        "rules:\n  - name: 'ApiTests#misc'\n    areas: [esignature]\n    endpoints: ['/api/sign']\n")
    idx = TestIndex(build_test_index("o/r", tmp_path))
    t = idx.by_id["p.ApiTests#misc"]
    assert t.areas[0] == "esignature" and "/api/sign" in t.endpoints
    assert idx.primary_framework == "testng"
