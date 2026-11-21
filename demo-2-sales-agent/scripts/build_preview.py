"""Build the hosted read-only preview of the dashboard.

Starts the API on a throwaway SQLite database, runs the agent twice with a few real reviews in
between (so approvals, the learning loop and the report all have something to show), saves every
answer the dashboard reads into demo-snapshot.json, then builds the frontend in preview mode into
preview-dist/. Open preview-dist/index.html through any static file server, or upload the folder.

Run from the demo folder with the backend's virtualenv active:

    python scripts/build_preview.py
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OUT = ROOT / "preview-dist"
REVIEWER = "Jordan Reyes"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    def __init__(self, base: str):
        self.base = base

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read() or b"null")

    def get(self, path: str):
        return self.call("GET", path)

    def post(self, path: str, body: dict | None = None):
        return self.call("POST", path, body)

    def run_agent(self) -> str:
        run_id = self.post("/api/agent/run")["run_id"]
        for _ in range(600):
            if self.get(f"/api/runs/{run_id}")["status"] != "running":
                return run_id
            time.sleep(0.5)
        raise RuntimeError("the agent run did not finish")


def stage(api: Api) -> None:
    """A realistic first week: one run, three reviews, one email sent, a second run that learned."""
    api.run_agent()
    pending = [d for d in api.get("/api/drafts") if d["kind"] == "outreach" and d["status"] == "pending"]
    first, second, third = pending[:3]
    api.post(f"/api/drafts/{first['id']}/approve", {"reviewer": REVIEWER})
    api.post(f"/api/drafts/{first['id']}/mark-sent", {"reviewer": REVIEWER})
    api.post(
        f"/api/drafts/{second['id']}/edit",
        {
            "subject": second["subject"],
            "body": (
                f"Hi {second['company']} team,\n\n"
                "Congratulations on the audit. Keeping that evidence current until the next one is the hard part, "
                "and it is the part Acme Guard does for you, read-only, from your cloud accounts.\n\n"
                "Want the one-page checklist we give teams for the months between audits?\n\n"
                f"{REVIEWER}\nAccount Executive, Acme Cloud Security"
            ),
            "reason": "Shorter, and lead with the checklist",
            "reviewer": REVIEWER,
        },
    )
    api.post(f"/api/drafts/{third['id']}/reject", {"reason": "Too long for a first email, and say what it costs", "reviewer": REVIEWER})
    api.run_agent()
    api.post("/api/automation/test-failure")


def snapshot(api: Api) -> dict:
    lists = ["/api/overview", "/api/runs", "/api/leads", "/api/accounts", "/api/drafts", "/api/icp", "/api/knowledge",
             "/api/learning", "/api/report/weekly", "/api/agent/context", "/api/notifications", "/api/automation-log", "/api/health"]
    snap = {path: api.get(path) for path in lists}
    for kind in ("runs", "leads", "accounts", "drafts"):
        for row in snap[f"/api/{kind}"]:
            path = f"/api/{kind}/{row['id']}"
            snap[path] = api.get(path)
    return snap


def main() -> None:
    port = free_port()
    workdir = Path(tempfile.mkdtemp(prefix="acme-preview-"))
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{workdir / 'preview.db'}", "PUBLIC_BASE_URL": f"http://127.0.0.1:{port}"}
    for key in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "SLACK_WEBHOOK_URL"):
        env.pop(key, None)  # the preview always uses the offline planner and the research cache
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        api = Api(f"http://127.0.0.1:{port}")
        for _ in range(120):
            try:
                api.get("/api/health")
                break
            except OSError:
                time.sleep(0.25)
        stage(api)
        snap = snapshot(api)
    finally:
        server.terminate()
        server.wait(timeout=20)
        shutil.rmtree(workdir, ignore_errors=True)

    npx = shutil.which("npx") or "npx"
    build_env = {**os.environ, "VITE_STATIC_PREVIEW": "1"}
    subprocess.run([npx, "tsc", "--noEmit"], cwd=FRONTEND, check=True)
    subprocess.run([npx, "vite", "build", "--outDir", str(OUT), "--emptyOutDir", "--base", "./"], cwd=FRONTEND, env=build_env, check=True)
    (OUT / "demo-snapshot.json").write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
    print(f"preview built in {OUT} ({len(snap)} saved answers)")


if __name__ == "__main__":
    main()
