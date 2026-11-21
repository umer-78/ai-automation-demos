"""Feedback loop: tone and targeting visibly change on the next run (before / after proof)."""

from __future__ import annotations

from app.agent.lessons import word_count
from tests.conftest import wait_for_run


def run(client):
    return wait_for_run(client, client.post("/api/agent/run").json()["run_id"])


def test_rejection_changes_the_next_draft_for_that_lead(client):
    run(client)
    before = client.get("/api/drafts?status=pending&kind=outreach").json()[0]
    reason = "Too long, and say what it costs."
    client.post(f"/api/drafts/{before['id']}/reject", json={"reason": reason, "reviewer": "Jordan"})
    second = run(client)
    assert second["lessons"]["max_words"] == 90 and second["lessons"]["include_price"]
    after = next(d for d in client.get("/api/drafts?kind=outreach").json() if d["previous_draft_id"] == before["id"])
    assert after["lead_id"] == before["lead_id"] and after["run_id"] == second["id"]
    assert word_count(after["body"]) < word_count(before["body"])
    assert "$1,500" in after["body"] and "$1,500" not in before["body"]
    assert {"short", "include_price"} <= set(after["lessons_applied"])
    learning = client.get("/api/learning").json()
    pair = learning["pairs"][0]
    assert pair["before"]["id"] == before["id"] and pair["after"]["id"] == after["id"]
    assert pair["feedback"]["reason"] == reason
    assert learning["runs"][-1]["avg_words"] < learning["runs"][0]["avg_words"]


def test_targeting_feedback_skips_large_companies_next_time(client):
    run(client)
    # approve nothing; reject one draft saying the company is too big (targeting feedback)
    draft = client.get("/api/drafts?status=pending&kind=outreach").json()[0]
    client.post(f"/api/drafts/{draft['id']}/reject", json={"reason": "Too big for us, skip large companies like this"})
    second = run(client)
    assert "1000+" in second["lessons"]["skip_size_bands"]
    new = [d for d in client.get("/api/drafts?kind=outreach").json() if d["run_id"] == second["id"]]
    for d in new:
        lead = client.get(f"/api/leads/{d['lead_id']}").json()
        assert lead["size_band"] != "1000+"


def test_not_a_fit_rejection_excludes_the_lead(client):
    run(client)
    draft = client.get("/api/drafts?status=pending&kind=outreach").json()[0]
    client.post(f"/api/drafts/{draft['id']}/reject", json={"reason": "Not a fit, they run everything on-premise"})
    lead = client.get(f"/api/leads/{draft['lead_id']}").json()
    assert lead["status"] == "excluded" and lead["excluded_reason"].startswith("Rejected by the rep")
    second = run(client)
    assert not any(d["lead_id"] == draft["lead_id"] for d in client.get("/api/drafts?kind=outreach").json() if d["run_id"] == second["id"])


def test_edits_are_stored_and_teach_length(client):
    run(client)
    draft = client.get("/api/drafts?status=pending&kind=outreach").json()[0]
    short = "\n".join(draft["body"].split("\n")[:3]) + "\n\nWant the checklist?\n\nJordan"
    resp = client.post(f"/api/drafts/{draft['id']}/edit", json={"subject": "Quick one", "body": short, "reason": "Shorter"})
    assert resp.status_code == 200 and resp.json()["status"] == "edited"
    detail = client.get(f"/api/drafts/{draft['id']}").json()
    assert detail["feedback"][0]["action"] == "edit" and detail["feedback"][0]["edited_body"] == short
    assert detail["original_body"] != detail["body"] and detail["has_recorded_approval"]
    ctx = client.get("/api/agent/context").json()
    assert "Rep's version" in ctx["feedback_block"] and ctx["lessons"]["max_words"] <= 90
    assert client.post(f"/api/drafts/{draft['id']}/edit", json={"subject": "Quick one", "body": short}).status_code == 422


def test_follow_up_sent_updates_the_crm(client):
    run(client)
    fu = client.get("/api/drafts?status=pending&kind=follow_up").json()[0]
    account_before = client.get(f"/api/accounts/{fu['account_id']}").json()
    client.post(f"/api/drafts/{fu['id']}/approve")
    client.post(f"/api/drafts/{fu['id']}/mark-sent", json={"reviewer": "Jordan"})
    account = client.get(f"/api/accounts/{fu['account_id']}").json()
    assert account["last_contact"] > account_before["last_contact"]
    assert account["activity"][0]["summary"].startswith("Email sent by Jordan")
