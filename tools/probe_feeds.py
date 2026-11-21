# -*- coding: utf-8 -*-
"""Probe candidate feeds: status, item count, sample title, dated ratio."""

import concurrent.futures as cf
import sys

import feedparser
import requests

CANDIDATES = {
    "thepaper": "https://www.thepaper.cn/rss/25950",
    "jiemian": "https://a.jiemian.com/index.php?m=article&a=rss",
    "ifeng_news": "https://news.ifeng.com/rss/index.xml",
    "huanqiu": "https://world.huanqiu.com/rss",
    "caixin": "https://www.caixin.com/rss/",
    "yicai": "https://www.yicai.com/rss/",
    "guancha": "https://www.guancha.cn/rss.xml",
    "chinanews_fin": "https://www.chinanews.com.cn/rss/finance.xml",
    "chinanews_ent": "https://www.chinanews.com.cn/rss/culture.xml",
    "xinhua": "http://www.xinhuanet.com/politics/news_politics.xml",
    "gnews_cn_nation": "https://news.google.com/rss/headlines/section/topic/NATION?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "gnews_cn_world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "gnews_en_world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    "axios": "https://api.axios.com/feed/",
    "diplomat": "https://thediplomat.com/feed/",
    "fp": "https://foreignpolicy.com/feed/",
    "scmp": "https://www.scmp.com/rss/91/feed",
    "reuters_world": "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
}

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}


def probe(name, url):
    try:
        resp = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return name, f"HTTP {resp.status_code}", 0, "", 0.0
        parsed = feedparser.parse(resp.content)
        entries = parsed.entries
        dated = sum(1 for e in entries if getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None))
        sample = entries[0].title[:54] if entries else ""
        ratio = dated / len(entries) if entries else 0.0
        return name, f"ok {len(entries)}", len(entries), sample, ratio
    except Exception as exc:  # noqa: BLE001
        return name, f"{type(exc).__name__}: {str(exc)[:40]}", 0, "", 0.0


def main():
    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        for name, status, count, sample, ratio in pool.map(lambda kv: probe(*kv), CANDIDATES.items()):
            print(f"{name:18} {status:22} dated={ratio:4.0%}  {sample}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
