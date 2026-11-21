# Airtable + Make.com setup (Module A)

The flow: a new row in Airtable → Airtable automation → Make.com webhook → Make router (one branch per
service) → the hub API (`/api/hooks/make/onboarding`) → task checklist, Slack welcome, Claude brief,
brief saved back to Airtable, email draft to the account manager. Setting Status to **Churned** runs
off-boarding the same way.

1. Create a free Airtable base, then create a personal access token with the scopes
   `data.records:read`, `data.records:write`, `schema.bases:write` for that base.
2. Create the table: `AIRTABLE_TOKEN=... AIRTABLE_BASE_ID=app... python airtable/setup_airtable.py`.
3. In Make.com, import `make/onboarding.blueprint.json` and `make/offboarding.blueprint.json`
   (Create scenario → ⋯ → Import Blueprint). Before importing, fill in your API address and token:
   `python make/build_blueprints.py --api https://<your-app>.onrender.com --token <HUB_API_TOKEN> --out /tmp/ready`.
4. In each scenario, click the webhook module → Add → copy the webhook URL. Turn both scenarios on.
5. In Airtable, add two automations, each with a "Run a script" action and an input variable
   `recordId`: `automation_new_client.js` (When record is created) and `automation_churned.js`
   (When Status is Churned). Paste the matching Make webhook URL at the top of each script.
6. Set `AIRTABLE_TOKEN`, `AIRTABLE_BASE_ID` and `HUB_API_TOKEN` on the server.

Test it: add a row in Airtable with Services = SEO. Within a minute the Slack welcome arrives, the
Brief column fills in, and the hub's automation log shows `onboarding … via Make.com`.
