"""One-off: write the five Actions secrets to the repo via the GitHub API.

Reads the token from GITHUB_TOKEN and the values from .env so nothing secret
ends up in the shell history or in git.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import requests
from nacl import encoding, public

REPO = "fffrogson/NewsPush"
SECRETS = ["DEEPSEEK_API_KEY", "SMTP_USER", "SMTP_PASS", "MAIL_TO", "BARK_URL"]


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def seal(public_key_b64: str, value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    return base64.b64encode(box.encrypt(value.encode())).decode()


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("missing GITHUB_TOKEN", file=sys.stderr)
        return 2
    env = load_env(Path(__file__).resolve().parent.parent / ".env")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    key_id = r.json()["key_id"]
    pk = r.json()["key"]
    failed = 0
    for name in SECRETS:
        value = env.get(name)
        if value is None:
            print(f"skip {name}: not in .env", file=sys.stderr)
            failed += 1
            continue
        body = {"encrypted_value": seal(pk, value), "key_id": key_id}
        resp = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{name}",
            headers=headers,
            data=json.dumps(body),
            timeout=30,
        )
        print(f"{name}: {resp.status_code}")
        if resp.status_code not in (201, 204):
            print(resp.text[:300], file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
