"""Scoring, guardrails, lessons, research and the ICP editor."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import respx

from app.agent.guardrails import check_follow_up, check_outreach, mentions_fact
from app.agent.lessons import Lessons, derive_lessons
from app.agent.scoring import DEFAULT_ICP, add_business_days, analyze_account, normalize_icp, score_lead
from app.services.research import TAVILY_URL, Research, normalize_url
from tests.conftest import make_settings, wait_for_run

TODAY = date(2026, 11, 17)


def test_lead_score_parts_and_reason():
    icp = normalize_icp(DEFAULT_ICP)
    attrs = {"category": "b2b_saas", "size_band": "200-499", "region": "Europe", "cloud_native": "yes"}
    facts = [{"fact": "Completed SOC 2 Type II.", "url": "https://x.com/a", "date": "2026-11-01", "type": "compliance"}]
    s = score_lead(attrs, facts, icp, TODAY)
    assert s["parts"] == {"fit": 50, "signals": 30, "recency": 20} and s["score"] == 100
    assert "Fit 50/50" in s["reason"] and "2 weeks old" in s["reason"]
    vendor = score_lead({**attrs, "category": "security_vendor"}, facts, icp, TODAY)
    assert vendor["excluded"] and vendor["score"] <= 20 and vendor["reason"].startswith("Excluded by the ICP")
    old = score_lead(attrs, [{**facts[0], "date": "2025-01-01"}], icp, TODAY)
    assert old["parts"]["recency"] == 2
    two = score_lead(attrs, facts + [{"fact": "Raised a Series B.", "url": "https://x.com/b", "date": "2026-10-01", "type": "funding"}], icp, TODAY)
    assert two["parts"]["signals"] == 30


def test_account_flags():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    icp = normalize_icp(DEFAULT_ICP)
    base = {"stage": "Proposal", "category": "fintech", "size": 300, "region": "Europe", "cloud_provider": "AWS",
            "deal_value": 48000, "notes": ""}
    stalled = analyze_account({**base, "stage_entered_at": now - timedelta(days=40), "last_contact": now - timedelta(days=5)}, icp, now)
    assert stalled["flags"] == ["stalled"]
    quiet = analyze_account({**base, "stage_entered_at": now - timedelta(days=40), "last_contact": now - timedelta(days=31)}, icp, now)
    assert quiet["flags"] == ["no_contact"]
    customer = {**base, "stage": "Customer", "plan": "Growth", "cloud_accounts_used": 18, "cloud_accounts_limit": 20,
                "renewal_date": (now + timedelta(days=200)).date(), "stage_entered_at": now - timedelta(days=300),
                "last_contact": now - timedelta(days=3)}
    assert analyze_account(customer, icp, now)["flags"] == ["upsell"]


def test_icp_normalisation_rejects_bad_values():
    icp = normalize_icp({"target_categories": ["b2b_saas", "nonsense"], "excluded_categories": ["b2b_saas"],
                         "employee_min": 500, "employee_max": 10, "regions": ["Mars", "Europe"],
                         "signal_weights": {"compliance": 99, "funding": "x"}})
    assert icp["target_categories"] == [] and icp["excluded_categories"] == ["b2b_saas"]
    assert icp["employee_min"] == 500 and icp["employee_max"] == 500
    assert icp["regions"] == ["Europe"] and icp["signal_weights"]["compliance"] == 30


def test_outreach_guardrails():
    lessons = Lessons()
    fact = "Completed a SOC 2 Type II audit in June."
    good = "Hi Keepit team,\n\nCongratulations on the SOC 2 Type II audit. Keeping evidence current between audits is where the hours go, and Acme Guard does that read-only from your cloud accounts.\n\nWant the checklist?\n\nJordan"
    assert check_outreach("After the audit", good, fact, lessons) == []
    assert any("email addresses" in e for e in check_outreach("Hi", good + " write to sam@keepit.com", fact, lessons))
    assert any("phone" in e for e in check_outreach("Hi", good + " Call +1 415 555 0100", fact, lessons))
    assert any("placeholders" in e for e in check_outreach("Hi", good.replace("Keepit team", "[First name]"), fact, lessons))
    assert any("mention the fact" in e for e in check_outreach("Hi", good.replace("SOC 2 Type II audit", "news"), fact, lessons))
    assert any("promise" in e for e in check_outreach("Hi", good + " We guarantee you pass.", fact, lessons))
    soft = Lessons(soft_cta=True)
    assert any("meeting" in e for e in check_outreach("Hi", good + " Book a 20-minute demo?", fact, soft))
    assert mentions_fact("the new CISO", "Appointed a new Chief Information Security Officer")


def test_follow_up_send_date_rules():
    lessons = Lessons()
    body = "Hi Maya,\n\nFollowing up on the proposal and the security review. I can send a one-page plan with the remaining steps.\n\nJordan"
    monday = date(2026, 11, 16)
    assert check_follow_up("Next steps", body, "Send the close plan", add_business_days(monday, 1), monday, lessons) == []
    assert any("weekday" in e for e in check_follow_up("Next steps", body, "Send the close plan", date(2026, 11, 21), monday, lessons))
    assert any("tomorrow" in e for e in check_follow_up("Next steps", body, "Send the close plan", monday, monday, lessons))
    assert add_business_days(date(2026, 11, 20), 1) == date(2026, 11, 23)  # Friday -> Monday


def test_lessons_from_feedback():
    items = [
        {"id": 3, "action": "edit", "reason": None, "draft_kind": "outreach",
         "original_body": " ".join(["word"] * 120) + " Would a 20-minute walkthrough next week work?",
         "edited_body": " ".join(["word"] * 60) + " Want the checklist?"},
        {"id": 2, "action": "reject", "reason": "Too big for us, they are a large enterprise", "draft_kind": "outreach"},
        {"id": 1, "action": "reject", "reason": "Pushy. No meeting asks please.", "draft_kind": "follow_up"},
    ]
    lessons = derive_lessons(items)
    assert lessons.soft_cta and lessons.max_words == 73  # 63 words kept + 10
    assert "1000+" in lessons.skip_size_bands
    keys = {r["key"] for r in lessons.rules}
    assert {"soft_cta", "skip_large", "rep_length"} <= keys


def test_tavily_search_and_fallback(tmp_path):
    settings = make_settings(tmp_path, tavily_api_key="tvly-test")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(TAVILY_URL).mock(return_value=httpx.Response(200, json={"results": [
            {"title": "Acme news", "url": "https://news.example.org/a", "content": "Raised a Series B.", "published_date": "2026-11-01"},
            {"title": "No url"},
        ]}))
        research = Research(settings)
        results = research.search("saas series b")
        assert route.calls[0].request.headers["Authorization"] == "Bearer tvly-test"
        assert [r["url"] for r in results] == ["https://news.example.org/a"] and results[0]["source"] == "web"


def test_failed_web_search_falls_back_to_the_cache(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with respx.mock(assert_all_called=False) as mock:
        mock.post(TAVILY_URL).mock(return_value=httpx.Response(432, text="usage limit"))
        with TestClient(create_app(make_settings(tmp_path, tavily_api_key="tvly-test"))) as c:
            run = wait_for_run(c, c.post("/api/agent/run").json()["run_id"])
            assert run["leads_scored"] >= 10
            assert any(t["tool"] == "search_web" and "(cache)" in t["result"] for t in run["tools_called"])


def test_normalize_url():
    assert normalize_url("HTTPS://Example.com/a/b/#frag") == "https://example.com/a/b"
    assert normalize_url("https://example.com/") == "https://example.com"


def test_icp_edit_preview_and_rescore(client):
    wait_for_run(client, client.post("/api/agent/run").json()["run_id"])
    icp = client.get("/api/icp").json()
    assert icp["active"]["author"] == "agent" and icp["active"]["version"] == 1
    criteria = {**icp["active"]["criteria"], "excluded_categories": ["security_vendor", "services", "fintech"]}
    criteria["target_categories"] = [c for c in criteria["target_categories"] if c != "fintech"]
    fintech = [l for l in client.get("/api/leads").json() if l["category"] == "fintech"]
    assert fintech
    preview = client.post("/api/icp/preview", json=criteria).json()
    assert preview["moved"] > 0
    assert all(l["status"] != "excluded" for l in client.get("/api/leads").json() if l["category"] == "fintech" and l["status"] != "drafted")
    saved = client.put("/api/icp", json={**criteria, "note": "No fintech this quarter"}).json()
    assert saved["saved"]["author"] == "rep" and saved["saved"]["version"] == 2
    after = [l for l in client.get("/api/leads").json() if l["category"] == "fintech"]
    assert all(l["score"] <= 20 for l in after)
    # the agent keeps the rep's ICP active on the next run
    wait_for_run(client, client.post("/api/agent/run").json()["run_id"])
    assert client.get("/api/icp").json()["active"]["version"] == 2
