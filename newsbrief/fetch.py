# -*- coding: utf-8 -*-
"""RSS ingestion: fetch every feed, normalise entries into Items."""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

from .models import FetchStat, Item

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "share_token", "fbclid", "gclid", "ref", "ref_src",
    "cmpid", "ocid", "ns_campaign", "ns_mchannel", "ns_source", "ito",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Curly quotes get rendered by CJK fallback fonts with a wide advance, which
# shows up as "it' s" in mail clients. Normalise them up front.
_PUNCT = {
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "—",
    "\u00a0": " ", "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",
}


def clean_text(raw: str, limit: int = 600) -> str:
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = text.replace("\u3000", " ")
    for src, dst in _PUNCT.items():
        text = text.replace(src, dst)
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def norm_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, urlencode(query), ""))


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def fetch_one(feed: dict, timeout: int, allow_undated: bool, max_entries: int) -> tuple[list[Item], FetchStat]:
    stat = FetchStat(feed_id=feed["id"], name=feed["name"], ok=False)
    try:
        resp = requests.get(
            feed["url"],
            timeout=timeout,
            headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
        )
        if resp.status_code != 200:
            stat.error = f"HTTP {resp.status_code}"
            return [], stat

        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            stat.error = f"解析失败: {parsed.get('bozo_exception')}"
            return [], stat

        items: list[Item] = []
        for entry in parsed.entries[:max_entries]:
            title = clean_text(entry.get("title", ""), 300)
            if not title:
                continue
            link = norm_url(entry.get("link", ""))
            published = _entry_time(entry)
            if published is None:
                if not allow_undated:
                    continue
                published = datetime.now(timezone.utc)

            raw_summary = entry.get("summary") or ""
            if not raw_summary and entry.get("content"):
                try:
                    raw_summary = entry["content"][0].get("value", "")
                except (IndexError, TypeError, KeyError):
                    raw_summary = ""
            lead = clean_text(raw_summary, 500)
            if lead and lead.startswith(title[:20]):
                lead = lead[len(title):].strip()

            fingerprint = link or f"{feed['id']}:{title}"
            uid = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]

            items.append(
                Item(
                    uid=uid,
                    title=title,
                    url=link,
                    source_id=feed["id"],
                    source_name=feed["name"],
                    published=published,
                    lead=lead,
                    lang=feed["lang"],
                    weight=feed["weight"],
                )
            )

        stat.ok = True
        stat.count = len(items)
        return items, stat
    except requests.RequestException as exc:
        stat.error = f"{type(exc).__name__}"
        return [], stat
    except Exception as exc:  # noqa: BLE001 - one bad feed must not kill the run
        stat.error = f"{type(exc).__name__}: {exc}"
        return [], stat


def fetch_all(feeds: list[dict], *, timeout: int = 20, workers: int = 10,
              allow_undated: bool = False, max_entries: int = 60) -> tuple[list[Item], list[FetchStat]]:
    items: list[Item] = []
    stats: list[FetchStat] = []

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(fetch_one, feed, timeout, allow_undated, max_entries): feed
            for feed in feeds
        }
        for future in cf.as_completed(futures):
            feed = futures[future]
            try:
                feed_items, stat = future.result()
            except Exception as exc:  # noqa: BLE001
                feed_items, stat = [], FetchStat(feed["id"], feed["name"], False, 0, str(exc))
            items.extend(feed_items)
            stats.append(stat)
            if stat.ok:
                log.info("  %-18s %3d 条", feed["name"], stat.count)
            else:
                log.warning("  %-18s 失败: %s", feed["name"], stat.error)

    # de-duplicate identical urls inside the same fetch
    seen: set[str] = set()
    unique: list[Item] = []
    for item in items:
        if item.uid in seen:
            continue
        seen.add(item.uid)
        unique.append(item)

    return unique, stats
