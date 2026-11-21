# Northwind Automation Hub: one page

**For:** digital agencies that onboard clients by hand and build ad reports from exports.

**Live demo:** https://automation-hub-production-0b8f47e0.up.railway.app

## The problem

Every new client means the same checklist, the same brief and the same Slack messages, typed
again by an account manager. Reporting means downloading exports from Google Ads, Meta and
Search Console every week and pasting them into a sheet. A cost spike is noticed when the
client notices it.

## What the hub does

* **Onboarding without manual steps.** A new row in Airtable (or one form in the hub) routes the
  client by service, creates their checklist, writes their brief from their website and posts
  the welcome in Slack.
* **One live report.** Spend, clicks, conversions and cost per conversion for every client,
  pulled every hour from Google Ads, Meta Ads, Search Console and Google Analytics. Exports from
  any other platform can be imported as a CSV.
* **Alerts that mean something.** A campaign is flagged only when its cost per conversion rises
  more than 25% week on week and the drop in conversions is statistically real, not noise.
* **Weekly summaries** in three plain sentences per client, ready to forward.
* **Nothing fails quietly.** Every step is logged and every failure is posted to Slack.

## What you need

A Google account that can see your clients' ad and analytics accounts, a Meta Business system
user, Airtable, Slack and, optionally, Make.com and a Claude API key. Every key is pasted on the
Settings page and stored encrypted. Your client data stays behind an access code.

## How it is delivered

1. Deployed on your own Railway or Render account with your own database.
2. Your Airtable base and Make.com scenarios set up from the included blueprints.
3. Your accounts connected and each client linked to their ad accounts.
4. A walkthrough with your team, and the full source code in your repository.

Built by Umer Hashmi, github.com/umer-78.
