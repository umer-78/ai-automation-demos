# How an automation hub like this would work for your agency

**The problem.** Account managers retype each new client's details into five tools, copy ad numbers into spreadsheets by hand, and find out a campaign went wrong when the client asks about it.

**What it does.**

- **Onboarding in under a minute.** Add a client in Airtable (or a form) and the hub creates the task checklist, posts a Slack welcome, writes a client brief with Claude, saves it back to Airtable and drafts an email to the account manager.
- **Reporting without spreadsheets.** A daily job pulls Google Ads and Meta results into one database, safely re-runnable with no double counting. The dashboard shows the last 30 days by day, channel and client, and flags any client whose cost per conversion rises more than 25% week on week. Claude writes a three-sentence summary per client each week.
- **Website drafts for pitches.** Business name, industry, tone and services go in; a one-page draft comes out, ready to edit section by section.
- **Nothing fails silently.** Every automation writes success or failure to a log, and failures post to Slack.

**How it fits your stack.**

| You use | How it connects |
|---|---|
| Airtable or a CRM | New and churned clients trigger Make.com scenarios (blueprints included) |
| Google Ads and Meta | Native CSV exports work today; API connections replace them when you're ready |
| Slack and email | Welcomes, alerts and account-manager drafts |
| Supabase | One Postgres database for clients, performance, logs and drafts |

**What we need from you.** Read access to one Airtable base, Slack webhook access, an export or API access for one ad account per platform, your onboarding checklist, and the brief template your team uses.

**Timeline.** Week 1: onboarding flow live on your Airtable and Slack. Week 2: reporting on your real ad accounts, with alert thresholds tuned to your clients. Week 3: weekly summaries, website drafts and hand-over.

**Running costs.** Make.com, Supabase, Airtable and the hosting fit free plans for a pilot. Claude is billed per token for briefs, summaries and drafts.

**Reading the sample.** The demo's five clients are fictional. Their ad numbers are priced from LocaliQ's published 2026 benchmarks for each industry, so the dashboard looks like a real agency's, and one cost spike is planted so the alert has something to catch.
