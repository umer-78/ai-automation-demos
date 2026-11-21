"""Acceptance tests for the sales agent, mapped to the spec's acceptance list."""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import agent, seed
from app.config import Settings
from app.db import activity_log, agent_runs, feedback, make_engine
from app.main import create_app
from app.research import SNAPSHOT

TODAY = date(2026, 11, 21)
APP_DIR = Path(__file__).resolve().parent.parent / "app"


def settings(tmp_path, **kw) -> Settings:
    base = dict(database_url=f"sqlite:///{tmp_path / 'agent.db'}", anthropic_api_key="", tavily_api_key="",
                slack_webhook_url="", frontend_dist=str(tmp_path / "no-dist"), rate_limit_per_minute=500,
                offline_step_s=0, seed_first_run=False)
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(settings(tmp_path), today_fn=lambda: TODAY))


def wait(client: TestClient, run_id: int, timeout: float = 60) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        run = client.get(f"/api/agent/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def run(client: TestClient) -> dict:
    r = client.post("/api/agent/run")
    assert r.status_code == 200, r.text
    return wait(client, r.json()["run_id"])


# ------------------------------------------------------------------------------------- CRM

def test_crm_has_50_accounts_with_exact_flags(client):
    s = client.get("/api/accounts").json()["summary"]
    assert s["total"] == 50
    assert s["by_stage"] == {"Prospecting": 16, "Proposal": 12, "Negotiation": 8, "Customer": 14}
    assert (s["stalled"], s["untouched"], s["upsell"]) == (8, 6, 5)


def test_crm_ages_roll_forward_with_the_calendar(tmp_path):
    s = settings(tmp_path)
    TestClient(create_app(s, today_fn=lambda: TODAY))
    later = TestClient(create_app(s, today_fn=lambda: TODAY + timedelta(days=10)))
    summ = later.get("/api/accounts").json()["summary"]
    assert (summ["stalled"], summ["untouched"]) == (8, 6)


def test_every_account_scored_with_a_reason(client):
    accts = client.get("/api/accounts").json()["accounts"]
    assert all(0 <= a["score"] <= 100 and a["score_reason"] for a in accts)
    assert accts == sorted(accts, key=lambda a: (-a["score"], a["id"]))


# ------------------------------------------------------------------------ one-click run

def test_one_click_run_meets_the_acceptance_bar(client):
    t0 = time.monotonic()
    result = run(client)
    assert result["status"] == "succeeded", result.get("error")
    assert time.monotonic() - t0 < 180
    leads = client.get("/api/leads").json()
    assert len(leads) >= 10
    for lead in leads:
        assert 0 <= lead["score"] <= 100 and lead["score_reason"] and lead["reason"]
        assert lead["source_url"].startswith("https://") and lead["fact_url"].startswith("https://")
    snapshot_urls = {r["url"] for q in SNAPSHOT["queries"] for r in q["results"]}
    assert {l["source_url"] for l in leads} <= snapshot_urls  # nothing invented
    queue = client.get("/api/drafts").json()
    first = [d for d in queue if d["kind"] == "first_touch"]
    assert len(first) == 5
    lead_urls = {l["id"]: {l["fact_url"], l["source_url"]} for l in leads}
    for d in first:
        assert d["fact_url"] in lead_urls[d["lead_id"]] and d["fact"]
        assert d["status"] == "pending"
    follow = [d for d in queue if d["kind"] == "follow_up"]
    assert len(follow) == 3 and all(d["due_date"] and d["next_step"] for d in follow)
    assert set(result["tools_called"]) == set(agent.HANDLERS)
    assert "Nothing was sent" in result["outcome"]


def test_top_five_leads_get_the_drafts(client):
    run(client)
    leads = client.get("/api/leads").json()
    drafted = {d["lead_id"] for d in client.get("/api/drafts").json() if d["kind"] == "first_touch"}
    assert drafted == {l["id"] for l in leads[:5]}


def test_security_vendors_are_excluded(client):
    run(client)
    names = {l["company"] for l in client.get("/api/leads").json()}
    assert not names & {"Reco", "Keepit"}


def test_every_run_is_logged_with_its_tools(client):
    run(client)
    runs = client.get("/api/agent/runs").json()
    assert runs[0]["tool_counts"]["save_lead"] >= 10 and runs[0]["tool_counts"]["web_search"] >= 3
    assert runs[0]["finished_at"]


def test_live_events_stream_ends(client):
    run_id = run(client)["id"]
    with client.stream("GET", f"/api/agent/runs/{run_id}/events") as r:
        text = "".join(r.iter_text())
    assert text.count("data: ") > 10 and "event: end" in text


def test_second_run_is_refused_while_one_runs(client):
    assert agent._run_lock.acquire(blocking=False)
    try:
        assert client.post("/api/agent/run").status_code == 409
    finally:
        agent._run_lock.release()


def test_failed_run_is_logged_and_alerted(client, monkeypatch):
    monkeypatch.setattr(agent, "run_offline", lambda ctx, fb: (_ for _ in ()).throw(RuntimeError("boom")))
    result = run(client)
    assert result["status"] == "failed" and "boom" in result["error"]
    with client.app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(activity_log).where(activity_log.c.status == "failure")).scalar() == 1


# ---------------------------------------------------------------------------- approvals

def test_approve_edit_reject_and_the_send_guard(client):
    run(client)
    a, b, c = client.get("/api/drafts").json()[:3]
    assert client.get(f"/api/drafts/{a['id']}/eml").status_code == 409  # not approved yet: can't leave the system
    assert client.post(f"/api/drafts/{a['id']}/approve").json()["status"] == "approved"
    eml = client.get(f"/api/drafts/{a['id']}/eml")
    assert eml.status_code == 200 and "X-Approved-At" in eml.text
    edited = client.post(f"/api/drafts/{b['id']}/edit", json={"subject": "Quick question", "body": "Hi team,\n\nShort and plain.\n\nSara"}).json()
    assert edited["status"] == "edited" and edited["original_subject"] == b["subject"]
    assert any(d["id"] == b["id"] for d in client.get("/api/drafts").json())  # still actionable
    assert client.get(f"/api/drafts/{b['id']}/eml").status_code == 409
    assert client.post(f"/api/drafts/{c['id']}/reject", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/drafts/{c['id']}/reject", json={"reason": "Too long and salesy"}).json()["status"] == "rejected"
    assert client.post(f"/api/drafts/{c['id']}/approve").status_code == 409
    with client.app.state.engine.connect() as conn:
        ids = [r[0] for r in conn.execute(select(feedback.c.id))]
    assert len(ids) == 3 and all(re.fullmatch(r"[0-9a-f-]{36}", i) for i in ids)


def test_no_code_path_can_send(client):
    assert not [t["name"] for t in agent.TOOLS if re.search(r"send|mail|post|message", t["name"])]
    source = "".join(p.read_text() for p in APP_DIR.glob("*.py"))
    assert "smtplib" not in source and "sendmail" not in source


def test_rejection_reason_reaches_the_next_run(client):
    run(client)
    target = client.get("/api/drafts").json()[0]
    before_words = len(target["body"].split())
    client.post(f"/api/drafts/{target['id']}/reject", json={"reason": "Too long. Keep it short and skip the meeting ask."})
    with client.app.state.engine.connect() as conn:
        lines = agent.feedback_lines(agent.feedback_context(conn))
    assert "Too long. Keep it short" in agent.system_prompt(None, lines, TODAY)
    second = run(client)
    assert second["feedback_used"] == 1
    notes = [e["summary"] for e in client.get(f"/api/agent/runs/{second['id']}").json()["events"]]
    assert any("Applying the rep's feedback" in n and "short" in n for n in notes)
    proof = client.get("/api/proof").json()
    assert proof and proof[0]["company"] == target["company"]
    assert len(proof[0]["after"]["body"].split()) < before_words
    assert "No call needed" in proof[0]["after"]["body"]


def test_rep_edited_profile_is_kept(client):
    icp = {"summary": "Fintech SaaS with 300 to 1,500 staff in the UK.", "industries": ["Fintech SaaS"],
           "size_min": 300, "size_max": 1500, "regions": ["UK"], "signals": ["compliance"], "exclusions": ["Banks"]}
    assert client.put("/api/icp", json=icp).json()["icp"]["edited_by"] == "rep"
    result = run(client)
    saved = client.get("/api/icp").json()["icp"]
    assert saved["summary"] == icp["summary"] and saved["edited_by"] == "rep"
    assert any("Kept the rep's edited" in e["summary"] for e in client.get(f"/api/agent/runs/{result['id']}").json()["events"])


# --------------------------------------------------------------------------- live agent

class FakeClaude:
    """Scripted stand-in for the Messages API: plays a full run, including two mistakes the tools must catch."""

    def __init__(self):
        self.messages = self
        self.turn = 0
        self.urls = [r["url"] for q in SNAPSHOT["queries"] for r in q["results"] if r["category"] == "saas"]

    def create(self, **kw):
        assert "no tool" not in kw["system"] and "cannot send" in kw["system"]
        self.turn += 1
        t = self.turn
        if t == 1:
            calls = [("read_business_notes", {}), ("save_icp", agent.DEFAULT_ICP)]
        elif t == 2:
            calls = [("web_search", {"query": q["query"]}) for q in SNAPSHOT["queries"]]
        elif t == 3:
            calls = [("save_lead", {"company": "Invented Ltd", "industry": "B2B SaaS", "source_url": "https://example.com/made-up",
                                    "reason": "Looks like a fit to me", "fact": "They are hiring a lot", "fact_url": "https://example.com/made-up",
                                    "signals": ["hiring_security"]})]
            calls += [("save_lead", {"company": f"Company {i}", "industry": "B2B SaaS", "employees": 400, "employees_source": "estimate",
                                     "source_url": u, "fact_url": u, "reason": "B2B SaaS with a buying signal", "fact": f"A real fact {i} from the page",
                                     "fact_date": "2026-11-02", "signals": ["compliance"]}) for i, u in enumerate(self.urls[:11])]
        elif t == 4:
            calls = [("finish", {"summary": "Done early."}), ("read_crm", {}), ("score_accounts", {})]
        elif t == 5:
            calls = [("create_draft", {"lead_id": i, "subject": f"Subject {i}", "body": "Hi team,\n\nA short, specific note about your audit and what we do.\n\nSara",
                                       "fact": "A real fact from the page", "fact_url": self.urls[i - 2]}) for i in range(2, 7)]
            calls.append(("create_draft", {"lead_id": 3, "subject": "Hi [Name]", "body": "Hi [Name], this has a placeholder in it, which is not allowed.",
                                           "fact": "A real fact from the page", "fact_url": self.urls[1]}))
        elif t == 6:
            calls = [("recommend_followup", {"account_id": "A004", "next_step": "Call the champion", "due_date": (TODAY + timedelta(days=3)).isoformat(),
                                             "subject": "Next step", "body": "Hi team,\n\nChecking in on the proposal and whether it still fits your plans.\n\nSara"}),
                     ("write_report", {}), ("finish", {"summary": "All done."})]
        else:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Done.")], usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        blocks = [SimpleNamespace(type="tool_use", id=f"t{t}-{k}", name=n, input=a) for k, (n, a) in enumerate(calls)]
        return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


def test_live_agent_loop_runs_real_tools_and_catches_mistakes(tmp_path, monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(agent, "make_client", lambda s: fake)
    c = TestClient(create_app(settings(tmp_path, anthropic_api_key="test-key"), today_fn=lambda: TODAY))
    result = run(c)
    assert result["status"] == "succeeded", result.get("error")
    assert result["engine"].startswith("live Claude") and result["input_tokens"] == 6000
    names = {l["company"] for l in c.get("/api/leads").json()}
    assert "Invented Ltd" not in names and len(names) == 11
    events = c.get(f"/api/agent/runs/{result['id']}").json()["events"]
    refusals = [e["summary"] for e in events if e["kind"] == "error"]
    assert any("Never invent URLs" in r for r in refusals)
    assert any("Not done yet" in r for r in refusals)
    assert any("placeholders" in r for r in refusals)
    assert len([d for d in c.get("/api/drafts").json() if d["kind"] == "first_touch"]) == 5


# ------------------------------------------------------------------------ report, safety

def test_weekly_report_renders_from_live_data(client):
    run(client)
    rep = client.get("/api/report").json()
    queue = client.get("/api/drafts").json()
    assert rep["counts"]["waiting"] == len(queue) == 8
    assert rep["counts"]["stalled"] == len(rep["stalled"]) == 8
    assert rep["counts"]["new_leads"] == len(client.get("/api/leads").json())
    scores = [l["score"] for l in rep["top_leads"]]
    assert scores == sorted(scores, reverse=True)


def test_security_headers_and_rate_limit(tmp_path):
    c = TestClient(create_app(settings(tmp_path, rate_limit_per_minute=3), today_fn=lambda: TODAY))
    r = c.get("/api/status")
    assert "default-src 'self'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    icp = {"summary": "A short profile for testing.", "industries": ["SaaS"], "size_min": 10, "size_max": 20}
    codes = [c.put("/api/icp", json=icp).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes


def test_status_is_honest_about_engines(client):
    s = client.get("/api/status").json()
    assert s["engine"] == agent.OFFLINE_ENGINE and not s["live_model"] and not s["live_search"]
    assert "snapshot" in s["research"] and s["snapshot_date"] == SNAPSHOT["taken_on"]


# ----------------------------------------------------------------------- real CRM exports

HUBSPOT = """Company name,Deal Stage,Last Activity Date,Date entered stage,Amount,Deal owner,Industry,Number of Employees,Description
Fjordline Analytics,Proposal Sent,2026-11-10,2026-09-30,"48,000",Ana Ruiz,SaaS,420,Waiting on security review
Brookhaven Payroll,Closed Won,2026-09-01,2025-03-01,36000,Ben Ito,Payroll SaaS,610,Healthy
Cinder Ops,Closed Lost,2026-10-01,2026-10-01,10000,Ana Ruiz,SaaS,80,Went with a competitor
Dalton Freight,Appointment Scheduled,2026-11-25,2026-11-01,20000,Ben Ito,Logistics,300,
"""


def test_real_crm_export_replaces_the_sample_and_keeps_real_dates(tmp_path):
    s = settings(tmp_path)
    c = TestClient(create_app(s, today_fn=lambda: TODAY))
    r = c.post("/api/crm/import", content=HUBSPOT.encode(), headers={"content-type": "text/csv"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["accounts"] == 2 and rep["skipped_count"] == 2
    reasons = " ".join(x["reason"] for x in rep["skipped"])
    assert "closed" in reasons and "future" in reasons
    accts = {a["company"]: a for a in c.get("/api/accounts").json()["accounts"]}
    assert set(accts) == {"Fjordline Analytics", "Brookhaven Payroll"}
    assert accts["Fjordline Analytics"]["stage"] == "Proposal" and "stalled" in accts["Fjordline Analytics"]["flags"]
    assert accts["Brookhaven Payroll"]["stage"] == "Customer" and "untouched" in accts["Brookhaven Payroll"]["flags"]
    assert c.get("/api/status").json()["crm_source"] == "import"
    later = TestClient(create_app(s, today_fn=lambda: TODAY + timedelta(days=30)))
    moved = {a["company"]: a for a in later.get("/api/accounts").json()["accounts"]}
    assert moved["Fjordline Analytics"]["last_contact"] == "2026-11-10"  # real dates never shift
    assert c.post("/api/crm/import", content=b"Name,Owner\nX,Y\n").status_code == 422


def test_offline_pacing_is_labelled(tmp_path):
    """A paced offline run still finishes, and its outcome says it was paced."""
    s = settings(tmp_path, offline_step_s=0.001)
    eng = make_engine(s.database_url)
    seed.ensure_seeded(eng, TODAY)
    run_id = agent.start_run(eng, s, TODAY, background=False)
    with eng.connect() as conn:
        row = conn.execute(select(agent_runs).where(agent_runs.c.id == run_id)).mappings().one()
    assert row["status"] == "succeeded"
    assert "paced so each step can be watched" in row["outcome"] and "Nothing was sent" in row["outcome"]


def test_first_start_seeds_one_offline_run(tmp_path):
    """A brand-new database opens with one logged offline run; restarting doesn't add another."""
    s = settings(tmp_path, seed_first_run=True, anthropic_api_key="sk-test-not-used")
    for _ in range(2):
        client = TestClient(create_app(s, today_fn=lambda: TODAY))
        runs = client.get("/api/agent/runs").json()
    assert len(runs) == 1 and runs[0]["status"] == "succeeded"
    assert runs[0]["engine"] == agent.OFFLINE_ENGINE and runs[0]["input_tokens"] == 0
    status = client.get("/api/status").json()
    assert status["counts"]["leads"] >= 10 and status["counts"]["waiting"] >= 5


def test_fact_dates_keep_their_precision(client):
    """A source dated only by month is shown as that month, never as an invented day."""
    run(client)
    leads = {l["company"]: l for l in client.get("/api/leads").json()}
    assert leads["dotCMS"]["fact_date"] == "2026-11-04" and leads["dotCMS"]["fact_precision"] == "day"
    assert "Raydar" not in leads, "a recruiter's posting is not the hiring company"
    assert all(l["fact_precision"] in ("day", "month", "year", "none") for l in leads.values())


@pytest.mark.parametrize("reason, want, never, shorter", [
    ("Too long. Keep it under 80 words and ask for a 15-minute call.", "15-minute call", "No call needed", True),
    ("Too pushy, don't ask for a meeting yet.", "No call needed", "minute call", False),
])
def test_offline_agent_follows_what_the_feedback_asks(client, reason, want, never, shorter):
    """'Ask for a call' and 'don't ask for a call' must not be read the same way."""
    run(client)
    first = next(d for d in client.get("/api/drafts").json() if d["kind"] == "first_touch")
    assert client.post(f"/api/drafts/{first['id']}/reject", json={"reason": reason}).status_code == 200
    run(client)
    again = next(d for d in client.get("/api/drafts").json() if d["kind"] == "first_touch" and d["lead_id"] == first["lead_id"])
    assert want in again["body"] and never not in again["body"]
    if shorter:
        assert len(again["body"].split()) < min(80, len(first["body"].split()))
