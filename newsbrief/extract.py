# -*- coding: utf-8 -*-
"""Article body extraction.

RSS gives us a headline and a one-sentence lead. That is not enough to write a
summary that says anything the headline didn't, so for the handful of stories we
actually push we go fetch the article and pull the main text out of the HTML.

trafilatura does the hard part; the regex path is a fallback for the odd page
where it returns nothing (JS-only pages, paywalls, odd markup).
"""

from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import requests

from .models import Item

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_DROP_RE = re.compile(
    r"(?is)<(script|style|noscript|nav|footer|header|aside|form|iframe|svg)[^>]*>.*?</\1>"
)
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_BLANK_RE = re.compile(r"[ \t\u00a0]+")
_NL_RE = re.compile(r"\n{3,}")


def _fallback_text(raw: str) -> str:
    """Crude but dependency-free: drop chrome, keep the text."""
    text = _DROP_RE.sub(" ", raw)
    text = re.sub(r"(?is)<br\s*/?>|</p>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _BLANK_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _NL_RE.sub("\n\n", text).strip()


def _trafilatura_text(raw: str, url: str) -> str:
    try:
        import trafilatura  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        return ""
    try:
        return trafilatura.extract(
            raw,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        ) or ""
    except Exception as exc:  # noqa: BLE001 - never let extraction break a run
        log.debug("trafilatura 失败 %s: %s", url, exc)
        return ""


def _tidy(text: str, limit: int) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        # prefer ending on a sentence boundary
        for mark in ("。", ".", "！", "?", "？"):
            pos = cut.rfind(mark)
            if pos > limit * 0.6:
                cut = cut[: pos + 1]
                break
        text = cut
    return text


_BROWSER = None
_PW = None
# Playwright's sync API is bound to the thread that started it, so every
# browser call is funnelled through one dedicated worker thread.
_BROWSER_POOL = None


def _browser_worker(url: str) -> str:
    global _BROWSER, _PW
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""
    try:
        if _BROWSER is None:
            _PW = sync_playwright().start()
            try:
                _BROWSER = _PW.chromium.launch(channel="msedge", headless=True)
            except Exception:  # noqa: BLE001 - msedge is Windows-only
                _BROWSER = _PW.chromium.launch(headless=True)
        page = _BROWSER.new_page(
            user_agent=UA, locale="zh-CN", viewport={"width": 1280, "height": 900}
        )
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            return page.content()
        finally:
            page.close()
    except Exception as exc:  # noqa: BLE001
        log.debug("浏览器兜底失败 %s: %s", url, exc)
        return ""


def _browser_text(url: str) -> str:
    """Last resort for pages that refuse plain HTTP requests (403 / JS-only)."""
    global _BROWSER_POOL
    if _BROWSER_POOL is None:
        _BROWSER_POOL = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="playwright"
        )
    try:
        return _BROWSER_POOL.submit(_browser_worker, url).result()
    except Exception as exc:  # noqa: BLE001
        log.debug("浏览器兜底异常 %s: %s", url, exc)
        return ""


def fetch_body(url: str, timeout: int = 15, limit: int = 2600) -> str:
    """Return the article's main text, or '' when we cannot get it."""
    if not url:
        return ""

    raw = ""
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
            },
        )
        if resp.status_code == 200:
            encoding = resp.encoding
            if not encoding or encoding.lower() in ("iso-8859-1", "ascii"):
                encoding = resp.apparent_encoding or "utf-8"
            raw = resp.content.decode(encoding, errors="ignore")
        else:
            log.debug("正文 HTTP %s %s", resp.status_code, url)
    except Exception as exc:  # noqa: BLE001 - paywalls, 403s, timeouts all fine
        log.debug("正文抓取失败 %s: %s", url, exc)

    text = _trafilatura_text(raw, url) if raw else ""
    if len(text) < 200:
        alt = _fallback_text(raw) if raw else ""
        if len(alt) > len(text):
            text = alt
    if len(text) < 200:
        html_alt = _browser_text(url)
        if html_alt:
            alt = _trafilatura_text(html_alt, url) or _fallback_text(html_alt)
            if len(alt) > len(text):
                text = alt
    return _tidy(text, limit)


def fill_bodies(items: list[Item], cfg: dict) -> None:
    """Fetch bodies for the selected items, in parallel, best effort."""
    if not cfg.get("enabled", True):
        return
    timeout = int(cfg.get("timeout", 15))
    limit = int(cfg.get("max_chars", 2600))
    workers = int(cfg.get("workers", 8))

    def work(item: Item) -> None:
        try:
            item.body = fetch_body(item.url, timeout=timeout, limit=limit)
        except Exception as exc:  # noqa: BLE001
            log.debug("正文异常 %s: %s", item.url, exc)
            item.body = ""

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, items))

    got = sum(1 for it in items if it.body)
    log.info("正文抓取：%d/%d 条成功", got, len(items))
