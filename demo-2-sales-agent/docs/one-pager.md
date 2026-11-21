# B2B Sales Agent: one page

**For:** B2B sales teams whose reps spend their mornings deciding who to call and what to say.

**Live demo:** https://sales-agent-production-68fda07e.up.railway.app

## The problem

Reps research prospects by hand, lose track of deals that have gone quiet, and write first
emails from scratch. The CRM knows which deals are stalling, but nobody reads it every day.

## What the agent does

* **Finds the right companies.** It learns your ideal customer from your product and deal notes,
  then searches the web for companies with a buying signal (a new security leader, a compliance
  milestone, funding, hiring). Every fact links to its source.
* **Reads your CRM.** It flags stalled deals, accounts nobody has contacted in 30 days and likely
  upsells, from HubSpot or a CRM export.
* **Scores everything from 0 to 100** with a reason a manager can check: fit, buying signals and
  recency, computed in code rather than guessed.
* **Drafts the emails.** First emails that use one real, sourced fact, and follow-ups with a send
  date. Nothing is sent: every draft waits for a rep to approve, edit or reject it.
* **Learns from your team.** Every edit and every rejection reason goes into the next run, and
  the change is shown side by side.
* **Reports weekly** on one page: new leads, top priorities, stalled deals, drafts waiting.

## What you need

A Claude API key, a Tavily search key, your product and deal notes, and either a HubSpot private
app token (read-only) or a CRM export. Keys are pasted on the Settings page and stored
encrypted. Your pipeline stays behind an access code.

## How it is delivered

1. Deployed on your own Railway or Render account with your own database.
2. Your notes, ideal customer profile and CRM loaded, and a first run reviewed with you.
3. Optional weekly schedule that runs the agent and posts the report to Slack.
4. A walkthrough with your team, and the full source code in your repository.

Built by Umer Hashmi, github.com/umer-78.
