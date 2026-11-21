# Demo 2: B2B Sales Agent (proof of concept)

An AI agent for a fictional seller, **Acme Cloud Security**. One click and it reads the product and
deal notes, writes an ideal customer profile, researches real companies on the web, analyses a
50-account CRM, scores everything from 0 to 100 with a plain-English reason, drafts personalised
first emails and follow-ups, and prepares a one-page weekly report.

A person approves every message. The agent has no tool that can send anything, and the app has no
email client at all: approved drafts are exported and sent by the rep from their own inbox.

![Overview: one click runs the agent; the radar shows every researched company by score and signal](docs/screenshots/overview.png)

## What it does

| Step | What happens | Where to see it |
| --- | --- | --- |
| 1. Learn the business | Reads `product.md`, `competitors.md` and 3 won + 3 lost deal notes, then saves an ideal customer profile (ICP). The rep can edit it; their version always wins. | Ideal customer |
| 2. Generate leads | Searches the web (Tavily) for real companies with a buying signal: SOC 2 or ISO 27001 milestones, a new CISO, security hiring, funding. Each lead is saved with its source URL and a one-line reason. | Leads |
| 3. Analyse the CRM | Flags the 8 stalled deals, the 6 accounts with no contact for 30+ days and the likely upsells. | CRM accounts |
| 4. Prioritise | Scores every lead and account 0 to 100: fit (up to 50) + buying signals (30) + recency (20), each with a plain-English reason. | Every list |
| 5. Draft outreach | Writes a first email for the top 5 leads, using one real fact from research and citing its source link. | Approval queue |
| 6. Recommend follow-ups | For accounts already in conversation: the next step, a send date (a weekday) and a draft. | Approval queue |
| 7. Report | One-page weekly summary from live data: new leads, top priorities, stalled deals, drafts waiting. Print, PDF, Markdown or Slack. | Weekly report |

Then the human part: **Approve**, **Edit** or **Reject** (with a one-line reason). Edits and reasons
go into the `feedback` table, the next run gets the last 20 of them in its prompt, and the change
shows up as a before and after draft.

![Approval queue: the cited fact and its source sit above every first email](docs/screenshots/approvals.png)

![Learning: the reviewer's reason, the rules it became and the rewritten draft](docs/screenshots/learning.png)

## Architecture

```mermaid
flowchart LR
    rep([Sales rep]) -- "Run agent" --> api[FastAPI service]
    cron([GitHub Actions, weekly]) -- "X-Automation-Key" --> api
    api --> runner[Agent runner]
    runner <-- "tool use loop" --> model["Anthropic Messages API"]
    runner --> tools{{"read_knowledge, save_icp, search_web, read_page, save_lead, analyze_crm, get_account_activity, list_leads, draft_outreach, draft_follow_up, finish"}}
    tools --> search["Tavily search, or the cached research file"]
    tools --> db[("Supabase Postgres: accounts, activity, leads, drafts, feedback, agent_runs, icp_versions, automation_log")]
    db --> queue[Approval queue]
    rep -- "approve, edit, reject" --> queue
    queue -- "feedback rows" --> db
    db -- "last 20 feedback items" --> runner
    queue -- "approved only" --> eml[".eml export, sent by the rep"]
    api -- "failures, weekly report" --> slack[(Internal Slack channel)]
```

* **Agent loop** (`backend/app/agent/runner.py`): the model calls the tools in a loop with prompt
  caching; network tools run in parallel, database writes stay sequential. A 150 second budget
  and a completion check guarantee the run delivers its targets inside 3 minutes, even if the
  model runs long or the API fails.
* **Offline mode**: without `ANTHROPIC_API_KEY` a deterministic planner calls the very same tools
  with template drafts, so the whole demo works with no keys. Without `TAVILY_API_KEY` research
  runs over `backend/data/research_snapshot.json`: 30 real companies with real public sources
  (press releases and news), gathered for this demo.
* **Scores are computed in code** from the ICP (`backend/app/agent/scoring.py`), never guessed by the
  model, so they are consistent and every point is explained.
* **Guardrails** (`backend/app/agent/tools.py`, `guardrails.py`): a fact can only cite a URL that
  search returned in that run; demo domains and existing CRM accounts are refused; first emails
  greet the team and may not contain names, email addresses, phone numbers or placeholders;
  every draft must mention the fact it cites; learned rules (length, no meeting ask, skip large
  companies) are enforced. A failed check goes back to the model as a tool error it can fix.
* **The safety rule is structural**: there is no send tool, no SMTP client, and
  `/api/drafts/{id}/eml` and `/mark-sent` refuse any draft without an approve or edit row in the
  `feedback` table. `tests/test_safety.py` checks all three.

## Set up (local, about 5 minutes)

1. `git clone https://github.com/umer-78/ai-automation-demos && cd ai-automation-demos/demo-2-sales-agent`
2. `python3.11 -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements-dev.txt`
3. `cd frontend && npm ci && npm run build && cd ..` (builds the dashboard into `backend/app/static`)
4. `cp .env.example .env` and, optionally, add `ANTHROPIC_API_KEY` and `TAVILY_API_KEY`
5. `cd backend && uvicorn app.main:app --reload`, then open http://localhost:8000 and click **Run agent**
6. `python -m pytest -q` runs the 33 tests (acceptance criteria, safety, learning loop, live loop with a scripted model)

For dashboard development run `npm run dev` in `frontend/` (port 5174, proxies `/api` to port 8001
by default; set `VITE_DEV_API=http://localhost:8000` to point it elsewhere).

## Deploy (free tiers)

1. **Supabase**: create a project, open the SQL editor and run `supabase/schema.sql`. Copy the
   *Session pooler* connection string (Project settings, Database).
2. **Render**: New, Blueprint, pick this repo. `render.yaml` creates the `acme-sales-agent` web
   service from the Dockerfile. Set `DATABASE_URL`, `PUBLIC_BASE_URL` (the service URL),
   `ANTHROPIC_API_KEY` and `TAVILY_API_KEY`. `AUTOMATION_API_KEY` and `ADMIN_TOKEN` are generated.
   Railway works the same way: new service from the repo, root directory `demo-2-sales-agent`,
   it detects the Dockerfile; add the same variables.
3. **Slack** (optional): add an incoming webhook for the sales team's channel as `SLACK_WEBHOOK_URL`.
4. **Weekly schedule** (optional): add repository secrets `ACME_URL` and `ACME_AUTOMATION_KEY`;
   `.github/workflows/acme-weekly.yml` runs the agent every Monday and posts the report to Slack.

Public demo guards: 6 agent runs per visitor per hour, at most 40 paid AI runs a day (extra runs
use the offline planner), and `POST /api/admin/reset` with `X-Admin-Token` reloads the CRM.

## Acceptance criteria

| Criterion | How it is met | Test |
| --- | --- | --- |
| One click gives at least 10 scored leads and 5 drafts in under 3 minutes | Offline runs take well under a second; live runs have a 150 s budget plus a fallback that fills any gap | `test_one_click_gives_10_scored_leads_and_5_drafts_fast`, `test_live_run_survives_an_api_outage` |
| Each score shows a reason; each draft cites its fact with a source link | Scores built in code with a sentence per part; drafts store `cited_fact` and `source_url` from the lead's own facts | `test_every_score_has_a_reason_and_every_draft_cites_a_sourced_fact` |
| No code path can send without a recorded approval | No send tool, no email client, export and mark-sent check the `feedback` table, not just a status column | `test_no_path_sends_without_a_recorded_approval`, `test_safety.py` |
| A rejected draft's reason appears in the next run's context | `agent_runs.context_feedback` stores exactly what the model was given | `test_rejected_reason_reaches_the_next_run` |
| Every agent run is logged with the tools it called | `agent_runs.tools_called`: tool, input, result, timing, who called it (AI, planner or fallback) | `test_every_run_is_logged_with_its_tool_calls` |
| The weekly report renders from live data | Built on request from the database | `test_weekly_report_renders_from_live_data` |
| Shared rule: failures are logged and alerted | `automation_log` + Slack alert, with a "Test a failure alert" button | `test_failures_are_logged_and_alerted` |

The suite also runs against Postgres (`TEST_DATABASE_URL=postgresql://... pytest`), which is what CI does.

## Data

* **Mock CRM**: `backend/data/crm_accounts.csv` and `crm_activity.csv` (50 fictional accounts,
  185 activities, 4 stages: 14 Prospect, 13 Discovery, 11 Proposal, 12 Customer). Dates are stored
  as "days ago", so the 8 stalled deals and 6 untouched accounts stay that way whenever you deploy.
  Regenerate with `python -m scripts.generate_crm`. Domains end in `.example`, so nothing can reach a real inbox.
* **Research cache**: `backend/data/research_snapshot.json`, 30 real companies with dated facts
  and source URLs. Profile fields the sources did not state are marked `unknown`, never guessed.
  No people's names are stored and drafts never address a named person.
* **Notes the agent reads**: `backend/app/knowledge/` (product, competitors, deal notes).

## Answers to the brief's open questions

* **Web search API**: Tavily. The free plan has 1,000 credits a month and a basic search costs 1
  credit; a run uses 3 to 6 searches. The cached research file keeps the demo working without a key.
* **Lovable or Replit**: neither was needed. The dashboard is React + Vite, built into the FastAPI
  service, so there is one deploy and one URL. It is plain React and Tailwind, so it can be
  moved into Lovable later if a client prefers.
* **Make.com blueprints**: in the repo as JSON for Demo 1 (`demo-1-automation-hub/make/`).

## API

Interactive docs at `/docs`. Main routes: `POST /api/agent/run`, `GET /api/runs/{id}`,
`GET /api/agent/context` (the exact prompt the next run will get), `GET /api/leads`,
`GET /api/accounts`, `GET /api/drafts`, `POST /api/drafts/{id}/approve|edit|reject|mark-sent`,
`GET /api/drafts/{id}/eml`, `GET|PUT /api/icp`, `POST /api/icp/preview`, `GET /api/learning`,
`GET /api/report/weekly(.md)`.

Built by [Umer](https://github.com/umer-78). MIT licence.
