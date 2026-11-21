# AI automation demos

Two complete builds for agencies and B2B sales teams. Each one runs on demo data out of the box,
switches to a client's real accounts from its Settings page, and is deployed live.

| Build | What it does | Live |
| --- | --- | --- |
| [**Northwind Automation Hub**](demo-1-automation-hub/) | Agency client onboarding with Airtable and Make.com, AI briefs and website drafts, and daily ad reporting from Google Ads, Meta Ads, Search Console and Analytics with tested cost alerts. | [Open](https://automation-hub-production-0b8f47e0.up.railway.app) |
| [**B2B Sales Agent**](demo-2-sales-agent/) | An agent that researches real companies, scores leads and CRM accounts, drafts outreach that a person approves, learns from every edit and reads HubSpot or a CRM export. | [Open](https://sales-agent-production-68fda07e.up.railway.app) |

![Northwind Automation Hub](demo-1-automation-hub/docs/screenshots/overview.png)

![B2B Sales Agent](demo-2-sales-agent/docs/screenshots/overview.png)

## What both builds have in common

* **Real numbers.** The hub's demo data follows published 2026 industry medians, each with its
  source. The agent researches real companies and every fact it uses links to the page it came
  from. Connect real accounts and the demo data is replaced.
* **A person stays in charge.** The sales agent has no way to send email; every draft waits for
  approval. The hub drafts briefs for the account manager instead of sending them to clients.
* **Nothing fails quietly.** Every run is logged step by step, and every failure is posted to
  Slack. Both apps have a button that forces a failure to prove it.
* **Private by default once real.** Loading real data locks the app behind an access code.
  API keys pasted in Settings are encrypted before they are stored and shown only as their last
  four characters.
* **Tested.** 73 tests for the hub and 49 for the agent, run on SQLite and Postgres in CI.

## Stack

Python 3.11, FastAPI and SQLAlchemy Core, Postgres (SQLite locally), the Anthropic API,
React 19, Vite, Tailwind and React Three Fiber, Docker. Each app is one service: the API also
serves the dashboard, with server-rendered titles, descriptions and JSON-LD per page.

## Run locally

Each folder has its own README with the full setup. The short version:

```bash
git clone https://github.com/umer-78/ai-automation-demos
cd ai-automation-demos/demo-1-automation-hub   # or demo-2-sales-agent
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
(cd frontend && npm ci && npm run build)
cd backend && uvicorn app.main:app --reload    # http://localhost:8000
```

No keys are needed: both apps run offline with template AI output and a simulated Slack feed.

## Deploy

On Railway, add one service per folder (root directory `demo-1-automation-hub` or
`demo-2-sales-agent`; each has a Dockerfile) and a Postgres database for each. On Render,
`render.yaml` creates both services in one step. The steps and variables are in each README.

Built by [Umer Hashmi](https://github.com/umer-78). MIT licence.
