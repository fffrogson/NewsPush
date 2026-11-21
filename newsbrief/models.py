# -*- coding: utf-8 -*-
"""Data structures passed between stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Item:
    """One RSS entry, before and after enrichment."""

    uid: str
    title: str
    url: str
    source_id: str
    source_name: str
    published: datetime
    lead: str = ""
    lang: str = "en"
    weight: float = 1.0

    # filled by later stages
    cluster: str = ""
    also_reported: list[str] = field(default_factory=list)
    score: float = 0.0
    category: str = ""
    reason: str = ""
    body: str = ""
    title_zh: str = ""
    summary: str = ""
    insight: str = ""
    terms: list[dict] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        """Chinese headline when we have one, original otherwise."""
        return self.title_zh or self.title

    @property
    def time_str(self) -> str:
        return self.published.strftime("%m-%d %H:%M")

    def to_prompt_dict(self) -> dict:
        return {
            "id": self.uid,
            "source": self.source_name,
            "title": self.title,
            "lead": self.lead[:280],
        }


@dataclass
class FetchStat:
    feed_id: str
    name: str
    ok: bool
    count: int = 0
    error: str = ""
