<!-- aiqip:pr-quality-report -->
## 🔴 AI Quality Gate: **BLOCK**
**example-org/clm-api-sample#101** - Add pre-validation for agreement renewal  
Risk score **69/100** · 4 files (+45/-2) · head `3f2a9c1e5b`

### Recommendation
- 1 regression test failure(s) classified as product regression or unexplained (e.g. com.example.clm.api.AgreementRenewalTests.renewUsesDefaultTerm).
- 1 high-severity test gap(s): Validation Rules & Callbacks.
- High change risk score 69/100 (highest functional-area criticality 3/3, no unit/integration test changes in the PR, 4 API endpoint(s) affected).

<sub>Evidence: Executed 3 regression test(s): 2 passed, 1 failed, 0 skipped. Linked Jira: SYNTH-101. Risk score 69/100.</sub>

### Change summary
4 files changed (+45/-2; 3 code, 1 config). Introduces 2 new type(s): IRenewalValidator, RenewalValidator. Primary functional areas: Amend, Renew, Terminate & Expire, Agreement / Contract Lifecycle, Validation Rules & Callbacks, Administration, Settings & Feature Flags. 4 API endpoint(s) affected.  
<sub>(deterministic summary - no LLM configured)</sub>

### Jira traceability
| Ticket | Type / Status | Summary | Alignment |
|---|---|---|---|
| [SYNTH-101](https://example.atlassian.net/browse/SYNTH-101) | Story / In Progress | Prevent renewal of terminated or expired agreements | **aligned** - 13 requirement terms found in the change (heuristic). |

### Change impact
**Functional areas:** Amend, Renew, Terminate & Expire, Agreement / Contract Lifecycle, Validation Rules & Callbacks, Administration, Settings & Feature Flags, Activation & Fully Signed, Integrations (CRM, Salesforce, Composer, X-Author, APIs)
**Risk factors:** highest functional-area criticality 3/3; no unit/integration test changes in the PR; 4 API endpoint(s) affected; 4 dependent component(s); configuration / feature-flag change; 2 similar historical customer defect(s)
<details><summary><b>Classes / types</b> (5)</summary>

- `IRenewalValidator`
- `RenewalValidator`
- `RenewalService`
- `Startup`
- `IRenewalService`

</details>
<details><summary><b>Methods</b> (4)</summary>

- `IRenewalValidator.Validate`
- `RenewalValidator.Validate`
- `RenewalService.RenewAsync`
- `Startup.ConfigureServices`

</details>
<details><summary><b>APIs</b> (4)</summary>

- `GET /api/clm/v1/agreements/{id} (AgreementsController.GetAgreement) [indirect]`
- `POST /api/clm/v1/agreements (AgreementsController.CreateAgreement) [indirect]`
- `POST /api/clm/v1/agreements/{id}/renew (AgreementsController.RenewAgreement) [indirect]`
- `POST /api/clm/v1/agreements/{id}/activate (AgreementsController.ActivateAgreement) [indirect]`

</details>
<details><summary><b>Configuration</b> (1)</summary>

- `src/Clm.Api/appsettings.json (modified, +2/-1)`

</details>
<details><summary><b>Feature flags</b> (1)</summary>

- `clm.renewal.preValidation (RenewalValidator.cs)`

</details>
<details><summary><b>Dependencies</b> (1)</summary>

- DI registration (Scoped): IRenewalValidator -> RenewalValidator

</details>
<details><summary><b>Dependents (blast radius)</b> (4)</summary>

- `IRenewalService <- src/Clm.Api/Controllers/AgreementsController.cs`
- `IRenewalService implemented by RenewalService (src/Clm.Api/Services/RenewalService.cs)`
- `UI example-org/clm-ui-sample: src/app/agreements/agreement.service.ts calls /api/clm/v1/agreements/${id}/activate`
- `UI example-org/clm-ui-sample: src/app/agreements/agreement.service.ts calls /api/clm/v1/agreements/${id}/renew`

</details>
<details><summary><b>Customer impact</b> (7)</summary>

- Requirement SYNTH-101 (Story, priority High) - Customer Account: Synthetic Customer Inc.
- Historical defect SYNTH-50 in a related area: Renewal fails for agreements with custom term picklist
- Historical defect SYNTH-61 in a related area: Activated agreement not published to search index
- Customer-critical capability touched: Amend, Renew, Terminate & Expire
- Customer-critical capability touched: Agreement / Contract Lifecycle
- Customer-critical capability touched: Validation Rules & Callbacks
- Customer-critical capability touched: Activation & Fully Signed

</details>

**Related historical customer defects**
- [SYNTH-50](https://example.atlassian.net/browse/SYNTH-50) Renewal fails for agreements with custom term picklist (Closed)
- [SYNTH-61](https://example.atlassian.net/browse/SYNTH-61) Activated agreement not published to search index (Closed)

**Product knowledge (business rules)**
- [Post-Contract Activation Actions](https://documentation.conga.com/en/clm-for-advantage-platform/current/clm-for-users/post-contract-activation-actions)
- [Configuring Duplicate Checks for Contract Requests](https://documentation.conga.com/en/clm-for-advantage-platform/current/clm-for-administrators/setup-and-configuration/contract-request-settings/configuring-duplicate-checks-for-contract-requests)
- [Contract Status Categories and Statuses](https://documentation.conga.com/en/clm-for-advantage-platform/current/clm-for-users/contract-management/contract-management/contract-creation/contract-status-categories-and-statuses)
- [Supplier Management](https://documentation.conga.com/en/clm-for-advantage-platform/current/clm-for-users/supplier-relationship-management/supplier-management)

### Regression scope & results
Executor `junit`: **2 passed, 1 failed, 0 skipped**
<details><summary><b>Selected tests</b> (5)</summary>

| Test | Why selected | Result |
|---|---|---|
| `com.example.clm.api.AgreementRenewalTests#renewActivatedAgreementWithTerm` | area: Agreement / Contract Lifecycle, Amend, Renew, Terminate & Expire, Activation & Fully Signed; calls impacted API /api/clm/v1/agreements/; keyword relevance 0.63 | ✅ passed |
| `com.example.clm.api.AgreementRenewalTests#renewUsesDefaultTerm` | area: Amend, Renew, Terminate & Expire, Agreement / Contract Lifecycle, Integrations (CRM, Salesforce, Composer, X-Author, APIs); calls impacted API /api/clm/v1/agreements/; keyword relevance 0.62 | ❌ failed |
| `features/amendment.feature:10` | area: Amend, Renew, Terminate & Expire, Agreement / Contract Lifecycle, Administration, Settings & Feature Flags; keyword relevance 1.00 | - |
| `features/amendment.feature:6` | area: Agreement / Contract Lifecycle, Amend, Renew, Terminate & Expire, Activation & Fully Signed; keyword relevance 0.39; smoke/critical tag | - |
| `com.example.clm.api.AgreementActivationTests#activateFullySignedAgreement` | area: Agreement / Contract Lifecycle, Activation & Fully Signed; calls impacted API /api/clm/v1/agreements/; smoke/critical tag | ✅ passed |

</details>

**Failure analysis**
- `com.example.clm.api.AgreementRenewalTests.renewUsesDefaultTerm` - **product-regression**: expected status 200 but was 400: Renewal validation failed: term is required

### Test gaps
- **high** · Validation Rules & Callbacks: No automation tests mapped to this impacted functional area.
- **medium** · unit tests: 1 new/changed type(s) without unit or integration tests in this PR (e.g. RenewalValidator).

<sub>AI Engineering Quality & Impact Platform v0.1.0 · 2026-10-26 08:53 UTC · Intelligence layer - code: example-org/clm-api-sample (6 files), example-org/clm-ui-sample (1 files) · tests: example-org/clm-automation-sample (6 tests, testng) · knowledge: 1206 CLM documentation pages · defects: 3 historical defects</sub>
