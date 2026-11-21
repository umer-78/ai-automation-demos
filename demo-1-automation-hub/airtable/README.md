# Airtable setup

Account managers add clients in one Airtable table. Adding a row starts onboarding; setting
Status to **Churned** starts off-boarding.

## 1. Create the Clients table

Import `Clients.csv` (**Add or import**, then **CSV**) into a new base, then set the field types:

| Field | Type | Notes |
| --- | --- | --- |
| Name | Single line text | primary field |
| Website | URL | |
| Industry | Single line text | |
| Services | Multiple select | options: `SEO`, `Paid Ads`, `Web Design` |
| Account Manager | Single line text | |
| Manager Email | Email | the brief draft is emailed here |
| Monthly Budget | Currency | optional, used for budget pacing |
| Status | Single select | `New`, `Onboarding`, `Active`, `Churned`, `Archived` (default `New`) |
| Source | Single line text | the hub sets `Hub form` for rows created from the dashboard |
| Simulate Failure | Checkbox | tick on a test row to prove the error route |
| Brief | Long text | written back by the hub |
| Hub Client ID | Number | written back by the hub |
| Onboarded At | Date | written back by the hub |

Create a personal access token at airtable.com/create/tokens with the scopes
`data.records:read`, `data.records:write` and `webhook:manage`, limited to this base.
Put it in `AIRTABLE_TOKEN`, and the base ID (starts with `app`) in `AIRTABLE_BASE_ID`.

## 2. Choose how Airtable triggers the flow

**Option A: webhook bridge (works on the Free plan).** Airtable Free automations cannot run
scripts, so they cannot call Make. Airtable's Webhooks API works on every plan:

```bash
curl -X POST "$PUBLIC_BASE_URL/api/admin/airtable/webhook" -H "X-Admin-Token: $ADMIN_TOKEN"
```

Airtable then pings `/api/webhooks/airtable` (signature checked) on every change. The hub
reads the changed rows and forwards them to the Make webhook (or runs the local orchestrator
when Make is not configured). A row is picked up once Name, Services and Account Manager are
filled and Status is `New`, so half-typed rows never start onboarding. Airtable webhooks
expire after 7 days unless refreshed; the daily GitHub Actions workflow refreshes it.

**Option B: automation scripts (Team plan and above).** Create two automations, each with a
"When a record matches conditions" trigger and a "Run a script" action:

- `onboarding-automation.js`: Status is `New` and Name, Services, Account Manager are not empty
- `offboarding-automation.js`: Status is `Churned`

Paste your Make webhook URL at the top of each script.

**Option C: the dashboard form.** "Add client" in the dashboard creates the Airtable row
(Source = `Hub form`) and starts onboarding straight away. The bridge and the automation
condition skip `Hub form` rows, so nothing runs twice.
