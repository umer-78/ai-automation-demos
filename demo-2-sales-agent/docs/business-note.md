# How a sales agent like this would work for your team

**The problem.** Reps spend hours a week finding companies worth contacting, checking the CRM for deals that went quiet, and writing first emails from scratch. Most of that is research and drafting, and it is where pipeline quietly leaks.

**What the agent does.** Each morning, or on demand, it:

- reads your positioning, pricing and recent won and lost deals, and keeps an ideal customer profile your team can edit;
- searches the web for companies showing your buying signals and saves only those with a real, linked source;
- scores every lead 0 to 100 and explains the score in plain words;
- reads every CRM account and flags stalled deals, accounts nobody has touched in a month, and expansion signals;
- drafts a short first email for the best leads and a follow-up for the most urgent accounts, each citing the fact it used;
- puts every draft in an approval queue. Nothing is sent without a person approving it, and that is enforced in code;
- learns from each edit and rejection, and writes a one-page weekly report.

**How it fits your stack.**

| You use | How it connects |
|---|---|
| HubSpot, Salesforce or Pipedrive | Start with a CSV export (works today); then read and write through the CRM's API |
| Gmail or Outlook | Approved emails open in your mail app; later, approved drafts can be placed in your drafts folder, never sent automatically |
| Slack | Alerts when a run fails; optionally a morning digest |
| Your own data | Product notes, case studies and deal notes are plain files the agent reads |

**What we need from you.** Your one-page positioning, pricing, three to six recent won and lost deals, the buying signals you trust, any companies or industries to avoid, and a read-only CRM export.

**Timeline.** Week 1: your notes, signals and a CRM export in place, first runs reviewed with a rep. Week 2: tune scoring and email style from the rep's feedback, connect the CRM API and Slack. Week 3: daily schedule, weekly report to the team, hand-over.

**Running costs.** Hosting and the database fit free plans for a pilot. Web search uses Tavily's free plan (1,000 credits a month, one per basic search). Claude is billed per token, and every run logs its token counts, so the cost per run is visible from day one.

**Safeguards.** No send path exists in the code. Sources must come from the run's own searches. Every tool call is logged. A failed run alerts you instead of failing silently.
