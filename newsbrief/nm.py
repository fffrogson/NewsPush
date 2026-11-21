# -*- coding: utf-8 -*-
"""News Minimalist source.

The site already ranks the day's news by significance and writes a short
summary for every story, so this module only *reads* it: no LLM, no scoring,
no rewriting.

Two transports are used because the site sits behind a bot challenge that
answers plain HTTP requests with 429 + a JavaScript checkpoint:

* ``requests`` first - cheap, and it works from hosts the challenge lets pass.
* Playwright (system Chrome/Edge, headless) as a fallback. The browser runs the
  challenge JavaScript, after which the same pages load normally.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

# A system proxy in the environment makes Chromium fail with
# net::ERR_CONNECTION_CLOSED against this host. Clear it before any transport.
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_key, None)
os.environ.setdefault("NO_PROXY", "*")

log = logging.getLogger(__name__)

BASE = "https://www.newsminimalist.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CHALLENGE_MARKERS = ("Vercel Security Checkpoint", "Just a moment", "cf-challenge")

JS_ITEMS = """() => [...document.querySelectorAll('details')].map(d => {
  const s = d.querySelector('summary');
  const spans = d.querySelectorAll('.mr-auto > span');
  const scoreEl = s && s.querySelector('span[title^="Significance"]');
  const dateEl = d.querySelector('.last-article-date');
  const src = [...d.querySelectorAll('a')].find(a => a.textContent.trim().startsWith('Source'));
  return {
    score: scoreEl ? scoreEl.textContent.trim() : '',
    title: spans[0] ? spans[0].textContent.trim() : '',
    meta: spans[1] ? spans[1].textContent.trim() : '',
    age: dateEl ? dateEl.textContent.trim() : '',
    stamp: dateEl ? (dateEl.getAttribute('title') || '') : '',
    source: src ? src.href : '',
  };
})"""

JS_TEXT = "() => document.body.innerText"

JS_SITEMAP = """() => {
  const t = document.body.innerText;
  const out = [];
  const re = /<loc>([^<]+)<\\/loc>[\\s\\S]*?<news:publication_date>([^<]+)<\\/news:publication_date>[\\s\\S]*?<news:title>([^<]+)<\\/news:title>/g;
  let m;
  while ((m = re.exec(t)) !== null) out.push([m[1], m[2], m[3]]);
  return out;
}"""


@dataclass
class Story:
    """One News Minimalist entry."""

    score: float
    title: str
    nm_url: str = ""
    source_url: str = ""
    domain: str = ""
    related: int = 0
    age: str = ""
    published: str = ""
    paragraphs: List[str] = field(default_factory=list)
    rank_pct: str = ""
    analysed: int = 0
    related_titles: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return " ".join(self.paragraphs).strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "title": self.title,
            "nm_url": self.nm_url,
            "source_url": self.source_url,
            "domain": self.domain,
            "related": self.related,
            "age": self.age,
            "published": self.published,
            "paragraphs": self.paragraphs,
            "rank_pct": self.rank_pct,
            "analysed": self.analysed,
        }


def slugify(text: str) -> str:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_score(text: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return float(match.group(1)) if match else 0.0


def parse_meta(meta: str) -> tuple[str, int]:
    """``(bbc.com + 49)`` -> ``("bbc.com", 49)``."""
    inner = (meta or "").strip().strip("()")
    match = re.match(r"([^\s+]+)\s*(?:\+\s*(\d+))?", inner)
    if not match:
        return "", 0
    return match.group(1), int(match.group(2) or 0)


# ---------------------------------------------------------------- transports


class FetchError(RuntimeError):
    pass


class Source:
    """Read-only client for newsminimalist.com."""

    def __init__(self, cfg: Dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        self.timeout = int(cfg.get("timeout") or 45)
        self.retries = int(cfg.get("retries") or 3)
        self.backoff = float(cfg.get("backoff") or 4)
        self.headless = bool(cfg.get("headless", True))
        self.channel = str(cfg.get("channel") or "msedge")
        self.ua = str(cfg.get("user_agent") or UA)
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._browser_broken = False
        self._http_blocked = False

    # -- cheap transport ---------------------------------------------------

    def _http(self, url: str, tries: int | None = None) -> Optional[str]:
        import requests

        if self._http_blocked:
            return None
        tries = tries or self.retries
        for attempt in range(tries):
            try:
                resp = requests.get(url, headers={"User-Agent": self.ua}, timeout=self.timeout)
            except Exception as exc:  # noqa: BLE001
                log.debug("http %s failed: %s", url, exc)
                time.sleep(min(self.backoff * (attempt + 1), 10))
                continue
            body = resp.text
            if resp.status_code == 200 and not any(m in body for m in CHALLENGE_MARKERS):
                return body
            if resp.status_code in (404, 410):
                return None
            # A bot challenge will not go away by asking again: switch to the
            # browser for the rest of this run instead of burning a timeout
            # on every sitemap shard.
            log.info("http blocked (%s on %s), switching to browser", resp.status_code, url)
            self._http_blocked = True
            return None
        return None

    # -- browser transport -------------------------------------------------

    def _ensure_page(self):
        if self._page is not None and not self._browser_broken:
            return self._page
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        kwargs = {"headless": self.headless, "args": ["--disable-blink-features=AutomationControlled"]}
        try:
            self._browser = self._playwright.chromium.launch(channel=self.channel, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.info("browser channel %s unavailable (%s), using bundled chromium", self.channel, exc)
            self._browser = self._playwright.chromium.launch(**kwargs)
        self._context = self._browser.new_context(locale="en-US", user_agent=self.ua)
        self._page = self._context.new_page()
        self._browser_broken = False
        return self._page

    def _goto(self, page, url: str) -> None:
        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                page.wait_for_timeout(1500)
                return
            except Exception as exc:  # noqa: BLE001
                last = exc
                log.debug("goto %s failed (%s/%s): %s", url, attempt + 1, self.retries + 1, exc)
                time.sleep(self.backoff * (attempt + 1))
        raise FetchError(f"cannot open {url}: {last}")

    def _browse(self, url: str, script: str):
        page = self._ensure_page()
        try:
            self._goto(page, url)
            return page.evaluate(script)
        except FetchError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("browser evaluate on %s failed: %s", url, exc)
            self._browser_broken = True
            raise FetchError(str(exc)) from None

    # -- public ------------------------------------------------------------

    def list_url(self, min_score: float, sort: str = "significance") -> str:
        query = f"?category=all&from={min_score:g}&to=10&sort={sort}"
        return BASE + "/" + query

    def fetch_list(self, min_score: float, sort: str = "significance") -> List[Story]:
        url = self.list_url(min_score, sort)
        raw: Optional[List[Dict[str, Any]]] = None
        body = self._http(url)
        if body:
            log.info("list via http")
            raw = self._items_from_html(body)
        if not raw:
            log.info("list via browser")
            raw = self._browse(url, JS_ITEMS)
        stories: List[Story] = []
        for row in raw or []:
            score = parse_score(row.get("score", ""))
            title = (row.get("title") or "").strip()
            if not title or score <= 0:
                continue
            domain, related = parse_meta(row.get("meta", ""))
            stories.append(
                Story(
                    score=score,
                    title=title,
                    source_url=row.get("source") or "",
                    domain=domain,
                    related=related,
                    age=row.get("age") or "",
                    published=row.get("stamp") or "",
                )
            )
        stories.sort(key=lambda s: s.score, reverse=True)
        log.info("list: %d stories with score >= %s", len(stories), min_score)
        return stories

    @staticmethod
    def _items_from_html(html: str) -> List[Dict[str, Any]]:
        """Fallback parser for the server-rendered list (used when HTTP works)."""
        rows: List[Dict[str, Any]] = []
        for block in re.findall(r"<details.*?</details>", html, re.S):
            score = re.search(r'title="Significance[^"]*"[^>]*>([^<]*)<', block)
            title = re.search(r'class="mr-auto"[^>]*>\s*<span[^>]*>([^<]+)<', block)
            meta = re.search(r'class="mr-auto"[^>]*>(?:\s*<span[^>]*>[^<]*</span>)\s*<span[^>]*>([^<]+)<', block)
            source = re.search(r'<a[^>]+href="([^"]+)"[^>]*>\s*Source', block)
            if not (score and title):
                continue
            rows.append(
                {
                    "score": score.group(1),
                    "title": title.group(1),
                    "meta": meta.group(1) if meta else "",
                    "source": source.group(1) if source else "",
                    "age": "",
                    "stamp": "",
                }
            )
        return rows

    def sitemap_urls(self, shards: int = 16) -> Dict[str, str]:
        """slug -> article url, from the news sitemaps."""
        mapping: Dict[str, str] = {}
        body = self._http(BASE + "/sitemap_index.xml")
        if body:
            locs = re.findall(r"<loc>([^<]+news-sitemaps/[^<]+)</loc>", body)
        else:
            locs = []
        if not locs:
            text = self._browse(BASE + "/sitemap_index.xml", JS_TEXT)
            locs = re.findall(r"<loc>([^<]+news-sitemaps/[^<]+)</loc>", text)
        locs = locs[:shards]
        log.info("sitemap shards: %d", len(locs))
        for shard in locs:
            rows: List[List[str]] = []
            body = self._http(shard)
            if body:
                rows = [
                    [loc, date, title]
                    for loc, date, title in re.findall(
                        r"<loc>([^<]+)</loc>[\s\S]*?<news:publication_date>([^<]+)</news:publication_date>"
                        r"[\s\S]*?<news:title>([^<]+)</news:title>",
                        body,
                    )
                ]
            if not rows:
                try:
                    rows = self._browse(shard, JS_SITEMAP)
                except FetchError as exc:
                    log.warning("shard %s skipped: %s", shard.rsplit("/", 1)[-1], exc)
                    continue
            for loc, _date, title in rows:
                mapping.setdefault(slugify(title), loc)
        log.info("sitemap: %d article urls", len(mapping))
        return mapping

    def map_stories(self, stories: List[Story], shards: int = 16) -> int:
        """Resolve article URLs shard by shard, stopping once every story is mapped."""
        if not stories:
            return 0
        pending = {id(s) for s in stories}
        body = self._http(BASE + "/sitemap_index.xml")
        if body:
            locs = re.findall(r"<loc>([^<]+news-sitemaps/[^<]+)</loc>", body)
        else:
            locs = []
        if not locs:
            try:
                text = self._browse(BASE + "/sitemap_index.xml", JS_TEXT)
                locs = re.findall(r"<loc>([^<]+news-sitemaps/[^<]+)</loc>", text)
            except FetchError as exc:
                log.warning("sitemap index unavailable: %s", exc)
                return 0
        locs = locs[:shards]

        for shard in locs:
            rows: List[List[str]] = []
            body = self._http(shard)
            if body:
                rows = [
                    [loc, date, title]
                    for loc, date, title in re.findall(
                        r"<loc>([^<]+)</loc>[\s\S]*?<news:publication_date>([^<]+)</news:publication_date>"
                        r"[\s\S]*?<news:title>([^<]+)</news:title>",
                        body,
                    )
                ]
            if not rows:
                try:
                    rows = self._browse(shard, JS_SITEMAP)
                except FetchError as exc:
                    log.warning("shard %s skipped: %s", shard.rsplit("/", 1)[-1], exc)
                    continue
            mapping: Dict[str, str] = {}
            for loc, _date, title in rows:
                mapping.setdefault(slugify(title), loc)
            self.match_titles([s for s in stories if id(s) in pending], mapping)
            pending = {id(s) for s in stories if not s.nm_url}
            log.info(
                "shard %s: %d urls, %d stories still unmatched",
                shard.rsplit("/", 1)[-1],
                len(mapping),
                len(pending),
            )
            if not pending:
                break
        return len(stories) - len(pending)

    @staticmethod
    def match_titles(stories: List[Story], mapping: Dict[str, str], threshold: float = 0.82) -> int:
        """Attach ``nm_url`` to each story, exact slug first then fuzzy."""
        slugs = list(mapping)
        normed = [(slug, slug.replace("-", " ")) for slug in slugs]
        hits = 0
        for story in stories:
            slug = slugify(story.title)
            url = mapping.get(slug)
            if not url:
                target = slug.replace("-", " ")
                best, best_ratio = "", 0.0
                for cand, text in normed:
                    if abs(len(text) - len(target)) > 24:
                        continue
                    ratio = difflib.SequenceMatcher(None, target, text).ratio()
                    if ratio > best_ratio:
                        best, best_ratio = cand, ratio
                if best and best_ratio >= threshold:
                    url = mapping[best]
            if url:
                story.nm_url = url
                hits += 1
        log.info("matched %d/%d stories to article pages", hits, len(stories))
        return hits

    def fetch_article(self, story: Story) -> Story:
        if not story.nm_url:
            return story
        text = ""
        body = self._http(story.nm_url)
        if body:
            text = re.sub(r"<[^>]+>", "\n", body)
        if not text.strip():
            try:
                text = self._browse(story.nm_url, JS_TEXT)
            except FetchError as exc:
                log.warning("article fetch failed: %s", exc)
                return story
        self._parse_article(story, text)
        return story

    @staticmethod
    def _parse_article(story: Story, text: str) -> None:
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        cut = next((i for i, line in enumerate(lines) if line in ("Share", "Share this")), len(lines))
        head = lines[:cut]
        body: List[str] = []
        for line in head:
            if line.startswith("Most significant articles"):
                break
            if re.match(r"^[A-Za-z0-9.-]+\.[a-z]{2,}( \(\w+\))? — ", line):
                story.published = line
                continue
            if line.startswith("With a significance score"):
                match = re.search(r"top ([\d.]+)%", line)
                story.rank_pct = match.group(1) if match else ""
                match = re.search(r"today's ([\d,]+)", line)
                story.analysed = int(match.group(1).replace(",", "")) if match else 0
                continue
            if story.title and line == story.title:
                continue
            if len(line) < 40:
                continue
            body.append(line)
        story.paragraphs = body[:4]

        # "With a significance score of 5.5, this news ranks in the top 1% of
        # today's 31530 analyzed articles." sits below the Share button.
        match = re.search(r"top ([\d.]+)%", text)
        story.rank_pct = match.group(1) if match else ""
        match = re.search(r"today's ([\d,]+)", text)
        story.analysed = int(match.group(1).replace(",", "")) if match else 0
        match = re.search(r"^([A-Za-z0-9.-]+\.[a-z]{2,}(?: \([^)]+\))?) — (.+)$", text, re.M)
        if match:
            story.published = f"{match.group(1)} · {match.group(2).strip()}"

    def close(self) -> None:
        for obj in (self._browser, self._playwright):
            try:
                if obj is self._browser and obj is not None:
                    obj.close()
                elif obj is not None:
                    obj.stop()
            except Exception:  # noqa: BLE001
                pass
        self._page = self._context = self._browser = self._playwright = None
