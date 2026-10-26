# Reference sample: congaengr/ROC-CLM-API#2248

"Pre and Post Validation For Contract Create and Generate Document Actions" (35 files, +3003/-20), linked to
[CONTRACTS-44346](https://conga.atlassian.net/browse/CONTRACTS-44346).

## Status: not run yet (blocked on access)

The dry run could not be executed from the environment this platform was built in:

```text
$ aiqip pr-quality --repo congaengr/ROC-CLM-API --pr 2248
== PR Quality Intelligence congaengr/ROC-CLM-API#2248 :: DRY RUN - nothing will be posted ==
error: GitHub 404 for /repos/congaengr/ROC-CLM-API/pulls/2248: repository or resource not found, or the token
has no access to it (private repos need a token with repo/contents scope and SSO authorization for the org).

$ aiqip doctor
GitHub congaengr/ROC-CLM-API        FAIL - GitHub 404 ...
GitHub congaengr/ROC-CLM-UI         FAIL - GitHub 404 ...
GitHub congaengr/rlpclm-automation  FAIL - GitHub 404 ...
Jira                                NOT CONFIGURED (JIRA_EMAIL / JIRA_API_TOKEN)
Index: knowledge                    1206 CLM documentation pages
```

* The three `congaengr` repositories are private and the build environment's GitHub token is not a member of the
  org (unauthenticated requests also return 404).
* `conga.atlassian.net` denies anonymous issue reads, and no Jira credentials were available.
* No sample report for PR 2248 is committed because producing one without the real diff and ticket would mean
  inventing data. The synthetic sample in `examples/output/` shows what the report looks like.

## How to produce the report (dry run, nothing is posted)

```bash
pip install -e .
export AIQ_GITHUB_TOKEN=ghp_...        # read access to congaengr/ROC-CLM-API, ROC-CLM-UI, rlpclm-automation (SSO-authorised)
export JIRA_EMAIL=you@conga.com JIRA_API_TOKEN=...   # https://id.atlassian.com/manage-profile/security/api-tokens
# optional LLM synthesis
export AIQ_LLM_PROVIDER=openai AIQ_LLM_API_KEY=... AIQ_LLM_MODEL=gpt-4o   # or azure-openai / anthropic

aiqip doctor                        # all checks should be OK
aiqip index code                    # ROC-CLM-API + ROC-CLM-UI (blobless clone, includes git ownership)
aiqip index tests                   # rlpclm-automation
aiqip index defects                 # dashboard 36628 filters -> JQL -> historical defects
aiqip pr-quality --repo congaengr/ROC-CLM-API --pr 2248 --out examples/pr-2248
```

This writes `examples/pr-2248/pr-quality-report.md` (the exact PR comment that would be posted) and
`pr-quality-report.json` (full evidence). Commit them as the reference output.

Alternatively run the **PR Quality Gate** workflow from the Actions tab of this repository with
`repo=congaengr/ROC-CLM-API`, `pr_number=2248`, `post=false` once the secrets listed in the main README are set.

To make the run reproducible offline afterwards:

```bash
aiqip snapshot pr --repo congaengr/ROC-CLM-API --pr 2248 --out examples/pr-2248/fixtures
aiqip snapshot jira --issue CONTRACTS-44346 --out examples/pr-2248/fixtures
aiqip pr-quality --repo congaengr/ROC-CLM-API --pr 2248 --fixtures examples/pr-2248/fixtures
```

(Check with your security team before committing raw PR/Jira payloads from private repositories.)

## What to expect for this PR

The PR title and description point at the *validation-rules*, *agreement-lifecycle* (contract create) and
*document-generation* functional areas, which are all customer-critical (criticality 3) in the taxonomy; with
35 files and +3003 lines the size factor is also high. Expect the risk score to land above the default
`high_risk_score` of 60, so the first run is likely to be **REVIEW** unless the selected regression tests are
executed and pass and the automation repo has tests mapped to validation rules. This is a prediction from the
PR metadata only, not an observed result.
