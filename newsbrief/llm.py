# -*- coding: utf-8 -*-
"""Thin OpenAI-compatible chat client (DeepSeek by default) with retries."""

from __future__ import annotations

import json
import logging
import re
import time

import requests

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", text, re.S)
    if fence:
        return fence.group(1).strip()
    return text.strip("`").strip()


def _tolerant_json(text: str) -> dict:
    """Parse model JSON, repairing the usual LLM slips."""
    cleaned = _strip_code_fence(text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"响应里没有 JSON: {cleaned[:200]!r}")
        candidate = cleaned[start : end + 1]
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # trailing commas
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON 解析失败: {exc}; 片段: {candidate[:200]!r}") from exc

    if isinstance(data, list):
        return {"items": data}
    if not isinstance(data, dict):
        raise LLMError(f"JSON 顶层类型异常: {type(data).__name__}")
    return data


class ChatClient:
    def __init__(self, cfg: dict):
        self.model = cfg.get("model") or "deepseek-flash"
        self.base = (cfg.get("api_base") or "https://api.deepseek.com").rstrip("/")
        self.key = cfg.get("api_key") or ""
        self.temperature = float(cfg.get("temperature", 0.3))
        self.max_tokens = int(cfg.get("max_tokens", 4000))
        self.timeout = int(cfg.get("timeout", 180))
        self.retries = int(cfg.get("retries", 3))
        self.json_mode = bool(cfg.get("json_mode", True))
        # DeepSeek-V4 系列默认开启思考模式（effort=high），思维链按输出计费且慢。
        # 打分/摘要不需要长推理，默认关掉；想开就设 ai.thinking: enabled。
        self.thinking = str(cfg.get("thinking", "disabled")).lower()

        # Token accounting, summed across every call in one run (cost estimation).
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cached_tokens = 0

        if not self.key:
            raise LLMError("缺少 API key：请设置 DEEPSEEK_API_KEY 或配置 ai.api_key")

    def usage_summary(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
        }

    def chat(self, system: str, user: str, *, json_mode: bool | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.thinking in ("enabled", "disabled"):
            payload["thinking"] = {"type": self.thinking}
        if json_mode if json_mode is not None else self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

        last_error = ""
        for attempt in range(1, self.retries + 1):
            try:
                resp = requests.post(
                    f"{self.base}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    content = body["choices"][0]["message"]["content"]
                    usage = body.get("usage") or {}
                    self.calls += 1
                    self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                    self.completion_tokens += int(usage.get("completion_tokens") or 0)
                    self.cached_tokens += int(
                        usage.get("prompt_cache_hit_tokens") or 0
                    )
                    log.info(
                        "  LLM ok  tokens in=%s (cached %s) out=%s",
                        usage.get("prompt_tokens", "?"),
                        usage.get("prompt_cache_hit_tokens", 0),
                        usage.get("completion_tokens", "?"),
                    )
                    return content
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise LLMError(last_error)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.retries:
                wait = 2 ** attempt
                log.warning("  LLM 第 %d 次失败(%s)，%ds 后重试", attempt, last_error, wait)
                time.sleep(wait)

        raise LLMError(f"LLM 调用失败: {last_error}")

    def chat_json(self, system: str, user: str) -> dict:
        return _tolerant_json(self.chat(system, user))
