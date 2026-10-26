# Triggering the Customer Track from Jira

Two options; both stay in dry-run unless posting is explicitly enabled.

## Option A - Jira Automation -> GitHub Actions (no server to host)

1. In this platform repo, create a fine-grained GitHub token (or GitHub App token) that can call
   `POST /repos/amvuggu-conga/AI-Engineering-Quality-and-Impact-platform/dispatches` (Contents: read & write
   on this repo). Store it in Jira Automation as a secret.
2. Jira project settings -> Automation -> Create rule:
   * Trigger: **Issue created** (optionally also *Issue transitioned* to "Open/Triage").
   * Condition: issue type = Bug, and e.g. label `customer_bug` / `escape_defect` or the customer field is set.
   * Action: **Send web request**
     * URL: `https://api.github.com/repos/amvuggu-conga/AI-Engineering-Quality-and-Impact-platform/dispatches`
     * Method: POST, headers `Accept: application/vnd.github+json`, `Authorization: Bearer {{secrets.AIQ_DISPATCH_TOKEN}}`
     * Body (custom data):
       ```json
       {"event_type": "jira-bug-created", "client_payload": {"issue_key": "{{issue.key}}", "post": false}}
       ```
       Set `"post": true` once the dry-run output has been reviewed and the team wants comments posted.
3. The `Jira Bug Analysis` workflow (`.github/workflows/jira-bug-analysis.yml`) runs, writes the analysis to the
   job summary and artifact, and (when `post` is true) adds the comment to the issue.

## Option B - Webhook server

Run `aiqip serve --port 8080` (container/VM with the same environment variables as the CLI) and point a Jira
Automation "Send web request" or a Jira system webhook at `https://<host>/webhooks/jira` with header
`X-AIQ-Token: <AIQ_JIRA_WEBHOOK_SECRET>`. Only issue types in `AIQ_JIRA_ISSUE_TYPES` (default `Bug`) are
processed. The same server accepts GitHub `pull_request` webhooks on `/webhooks/github`
(`AIQ_GITHUB_WEBHOOK_SECRET`). Set `AIQ_POST=true` to write results back.
