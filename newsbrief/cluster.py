# -*- coding: utf-8 -*-
"""Cross-source de-duplication: merge reports of the same story into one item."""

from __future__ import annotations

import re
from collections import defaultdict

from .models import Item

_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "had",
    "will", "would", "says", "said", "after", "over", "into", "about", "amid",
    "new", "news", "more", "than", "its", "his", "her", "their", "our", "you",
    "but", "not", "are", "was", "were", "been", "being", "they", "them", "what",
    "when", "where", "which", "who", "how", "why", "can", "could", "may", "might",
    "update", "live", "video", "watch", "breaking", "exclusive", "report",
}


def tokens(text: str) -> set[str]:
    """CJK bigrams + latin word tokens."""
    low = text.lower()
    out: set[str] = set()

    for run in re.findall(r"[\u4e00-\u9fff]+", low):
        for i in range(len(run) - 1):
            out.add(run[i : i + 2])
        if len(run) == 1:
            out.add(run)

    for word in _LATIN.findall(low):
        if len(word) >= 3 and word not in STOPWORDS:
            out.add(word)

    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter < 3:
        return 0.0
    return inter / len(a | b)


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def cluster(items: list[Item], *, threshold: float = 0.45) -> list[Item]:
    """Group near-identical titles, keep one representative per story."""
    if not items:
        return []

    token_sets = [tokens(f"{it.title} {it.lead[:120]}") for it in items]

    # Word frequency across the batch: a token shared by only a couple of items
    # is a strong signal (e.g. 神舟/舟二/二十 …), so it may merge weaker overlaps.
    freq: dict[str, int] = defaultdict(int)
    for ts in token_sets:
        for tok in ts:
            freq[tok] += 1

    def rare_shared(a: set[str], b: set[str]) -> bool:
        for tok in a & b:
            if freq[tok] > 2:
                continue
            if len(tok) >= 6 or (len(tok) == 2 and _CJK.match(tok)):
                return True
        return False

    uf = _UnionFind(len(items))

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i].url and items[i].url == items[j].url:
                uf.union(i, j)
                continue
            score = jaccard(token_sets[i], token_sets[j])
            if score >= threshold:
                uf.union(i, j)
            elif score >= 0.28 and rare_shared(token_sets[i], token_sets[j]):
                uf.union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(items)):
        groups[uf.find(idx)].append(idx)

    merged: list[Item] = []
    for root, members in groups.items():
        if len(members) == 1:
            rep = items[members[0]]
            rep.cluster = str(root)
            merged.append(rep)
            continue

        # keep the most authoritative source; tie-break on earliest publish time
        best = max(members, key=lambda k: (items[k].weight, -items[k].published.timestamp()))
        rep = items[best]
        rep.cluster = str(root)
        others = [items[k].source_name for k in members if k != best]
        rep.also_reported = sorted(set(others))

        # borrow a longer lead if the representative's is thin
        if len(rep.lead) < 120:
            longest = max((items[k] for k in members), key=lambda it: len(it.lead))
            if len(longest.lead) > len(rep.lead):
                rep.lead = longest.lead
        merged.append(rep)

    merged.sort(key=lambda it: it.published, reverse=True)
    return merged
