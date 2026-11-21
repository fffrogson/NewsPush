# -*- coding: utf-8 -*-
"""Config loading: YAML + ${ENV} expansion + optional .env file."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_dotenv(path: Path) -> None:
    """Minimal .env loader; existing environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


class Config:
    """Dotted-path access over the parsed YAML tree."""

    def __init__(self, data: dict, base_dir: Path):
        self.data = data
        self.base_dir = base_dir

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return default if node is None else node

    def section(self, path: str) -> dict:
        value = self.get(path, {})
        return value if isinstance(value, dict) else {}

    @property
    def feeds(self) -> list[dict]:
        out = []
        for i, raw in enumerate(self.get("feeds", []) or []):
            if not isinstance(raw, dict) or not raw.get("url"):
                continue
            if raw.get("enabled", True) is False:
                continue
            out.append(
                {
                    "id": raw.get("id") or f"feed{i}",
                    "name": raw.get("name") or raw["url"],
                    "url": raw["url"],
                    "lang": raw.get("lang", "en"),
                    "weight": float(raw.get("weight", 1.0)),
                }
            )
        return out


def load(path: str | Path) -> Config:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {cfg_path}")
    load_dotenv(cfg_path.parent / ".env")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return Config(_expand(raw), cfg_path.parent)
