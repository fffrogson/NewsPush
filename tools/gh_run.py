"""Trigger the daily-brief workflow and stream its status (one-off helper)."""
from __future__ import annotations

import json
import os
import sys
import time

import requests

REPO = "fffrogson/NewsPush"
WORKFLOW = "daily.yml"
PROXIES = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}


def api(path: str, method: str = "get", **kw):
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{REPO}{path}"
    fn = getattr(requests, method)
    return fn(url, headers=headers, proxies=PROXIES, timeout=60, **kw)


def main() -> int:
    dispatch = sys.argv[1] if len(sys.argv) > 1 else "no"
    if dispatch == "run":
        r = api(
            f"/actions/workflows/{WORKFLOW}/dispatches",
            "post",
            data=json.dumps({"ref": "main", "inputs": {"dry_run": "true", "limit": "5"}}),
        )
        print("dispatch:", r.status_code, r.text[:200])
        if r.status_code not in (204, 201):
            return 1
        time.sleep(8)
    runs = api(f"/actions/workflows/{WORKFLOW}/runs?per_page=3").json()
    for run in runs.get("workflow_runs", []):
        print(f"{run['id']} {run['status']}/{run.get('conclusion')} {run['created_at']} {run['html_url']}")
    if not dispatch.startswith("watch"):
        return 0
    run_id = runs["workflow_runs"][0]["id"]
    for _ in range(60):
        r = api(f"/actions/runs/{run_id}").json()
        print(f"status={r['status']} conclusion={r.get('conclusion')}")
        if r["status"] == "completed":
            jobs = api(f"/actions/runs/{run_id}/jobs").json()
            for job in jobs.get("jobs", []):
                for step in job.get("steps", []):
                    print(f"  {step['number']:2d} {step['name']}: {step['status']}/{step.get('conclusion')}")
            return 0 if r.get("conclusion") == "success" else 1
        time.sleep(10)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
