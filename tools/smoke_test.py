# -*- coding: utf-8 -*-
"""End-to-end smoke test with a fake LLM, so the scoring/summary code paths
and the HTML layout can be exercised without an API key.

Everything it writes is marked as sample content.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-fake-for-smoke-test")

import newsbrief.main as app  # noqa: E402


class FakeClient:
    def __init__(self, cfg):  # noqa: D401 - signature matches ChatClient
        self.calls = 0

    def usage_summary(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
        }

    @staticmethod
    def _pseudo(text: str) -> float:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return int(digest[:4], 16) / 0xFFFF

    def chat_json(self, system: str, user: str) -> dict:
        self.calls += 1
        rows = []
        if "重要性" in system and "复核" not in system:
            ids = [line.split("]")[0].lstrip("[") for line in user.splitlines() if line.startswith("[")]
            for raw in ids:
                title = ""
                for line in user.splitlines():
                    if line.startswith(f"[{raw}]"):
                        title = line
                        break
                score = round(1 + self._pseudo(title) * 8.6, 1)
                rows.append({
                    "id": int(raw),
                    "score": score,
                    "category": "科技" if "AI" in title else "社会",
                    "reason": "示例理由用于版式校验",
                })
        elif "复核" in system:
            ids = [line.split("]")[0].lstrip("[") for line in user.splitlines() if line.startswith("[")]
            for raw in ids:
                rows.append({
                    "id": int(raw),
                    "score": round(4.5 + self._pseudo(raw) * 4.5, 1),
                    "category": "社会",
                    "reason": "示例理由用于版式校验",
                })
        elif "中文新闻编辑" in system:
            ids = [line.split("]")[0].lstrip("[") for line in user.splitlines() if line.startswith("[")]
            for raw in ids:
                rows.append({
                    "id": int(raw),
                    "summary": f"（示例摘要 #{raw}）这里会是两句事实概括，用于校验排版与行距。",
                    "insight": "（示例解读）这里会是一句为什么值得知道。",
                })
        return {"items": rows}

    def chat(self, system: str, user: str, *, json_mode=None) -> str:
        return "（示例总览）这是用于版式校验的总览段落，正式运行时会由 AI 依据当天入选新闻生成，不超过三句话。"


def main() -> int:
    app.ChatClient = FakeClient  # type: ignore[assignment]
    return app.main(["--dry-run", "--out", "output-smoke"])


if __name__ == "__main__":
    sys.exit(main())
