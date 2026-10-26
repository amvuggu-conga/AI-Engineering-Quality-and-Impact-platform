from aiqip.analysis.diff import changed_members, split_unified_diff
from aiqip.intelligence.csharp import classify_path, parse_csharp, parse_json_config, parse_typescript

CONTROLLER = '''
using Microsoft.AspNetCore.Mvc;
namespace Conga.Clm.Api.Controllers
{
    [ApiController]
    [Route("api/clm/v{version:apiVersion}/[controller]")]
    public class ContractsController : ControllerBase
    {
        private readonly IContractValidationService _validation;

        [HttpPost("{id}/generate")]
        public async Task<IActionResult> GenerateDocument(string id, [FromBody] GenerateRequest req)
        {
            if (await _features.IsFeatureEnabledAsync("clm.contract.preValidation")) { }
            var timeout = _configuration["Generate:TimeoutSeconds"];
            return Ok();
        }

        [HttpPost]
        public async Task<IActionResult> Create([FromBody] CreateRequest req) => Ok();

        [HttpGet("~/api/health")]
        public IActionResult Health() => Ok();
    }
}
'''


def test_parse_csharp_extracts_types_routes_flags_config():
    facts = parse_csharp("src/Controllers/ContractsController.cs", CONTROLLER)
    assert facts.namespace == "Conga.Clm.Api.Controllers"
    assert facts.types[0]["name"] == "ContractsController"
    routes = {(e["method"], e["route"], e["action"]) for e in facts.endpoints}
    assert ("POST", "/api/clm/v{version:apiVersion}/Contracts/{id}/generate", "GenerateDocument") in routes
    assert ("POST", "/api/clm/v{version:apiVersion}/Contracts", "Create") in routes
    assert ("GET", "/api/health", "Health") in routes
    assert "clm.contract.preValidation" in facts.feature_flags
    assert "Generate:TimeoutSeconds" in facts.config_keys
    assert "IContractValidationService" in facts.identifiers


def test_parse_typescript_finds_consumed_endpoints():
    src = "export class AgreementService { renew(id) { return this.http.post(`/api/clm/v1/agreements/${id}/renew`, {}); } }"
    facts = parse_typescript("src/app/agreement.service.ts", src)
    assert facts.types[0]["name"] == "AgreementService"
    assert "/api/clm/v1/agreements/${id}/renew" in facts.consumed_endpoints


def test_parse_json_config_collects_feature_flags():
    facts = parse_json_config("appsettings.json", '{"FeatureFlags": {"clm.x": true}, "Db": {"Conn": "..."}}')
    assert "FeatureFlags:clm.x" in facts.feature_flags
    assert "Db:Conn" in facts.config_keys


def test_classify_path():
    assert classify_path("tests/Conga.Clm.Api.Tests/ContractTests.cs") == "test"
    assert classify_path("src/Conga.Clm.Api/appsettings.Development.json") == "config"
    assert classify_path("src/Conga.Clm.Api/Conga.Clm.Api.csproj") == "build"
    assert classify_path("src/Data/Migrations/20260101_Add.cs") == "migration"
    assert classify_path("src/Services/ContractService.cs") == "code"
    assert classify_path(".github/workflows/ci.yml") == "build"


PATCH = """@@ -10,6 +10,9 @@ namespace Conga.Clm.Api.Services
     public class ContractService : IContractService
     {
+        private readonly IPreValidator _pre;
@@ -40,7 +43,10 @@ public async Task<Contract> CreateAsync(CreateRequest request)
         {
-            var c = Map(request);
+            var result = await _pre.ValidateAsync(request);
+            if (!result.IsValid) throw new ValidationException(result.Message);
+            var c = Map(request);
"""


def test_changed_members_attributes_body_change_to_enclosing_method():
    members = changed_members("src/Services/ContractService.cs", PATCH)
    qualified = {m.qualified for m in members}
    assert "ContractService.CreateAsync" in qualified


def test_changed_members_new_file_lists_types_and_methods():
    patch = "@@ -0,0 +1,8 @@\n+namespace X\n+{\n+    public interface IPreValidator\n+    {\n+        Task<Result> ValidateAsync(CreateRequest r);\n+    }\n+    public sealed class PreValidator : IPreValidator { public async Task<Result> ValidateAsync(CreateRequest r) { } }\n+}"
    members = changed_members("src/Validation/PreValidator.cs", patch)
    kinds = {(m.kind, m.name) for m in members}
    assert ("interface", "IPreValidator") in kinds
    assert ("class", "PreValidator") in kinds
    assert any(m.name == "ValidateAsync" for m in members)


def test_split_unified_diff():
    diff = "diff --git a/a.cs b/a.cs\nindex 1..2 100644\n--- a/a.cs\n+++ b/a.cs\n@@ -1 +1 @@\n-x\n+y\n"
    assert split_unified_diff(diff) == {"a.cs": "@@ -1 +1 @@\n-x\n+y"}
