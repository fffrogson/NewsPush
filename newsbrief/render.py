# -*- coding: utf-8 -*-
"""Rendering: HTML email, plain text, Bark push body."""

from __future__ import annotations

import html
import re
from datetime import datetime

from .models import Item

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

DEFAULT_TIERS = [
    {"name": "重大", "min": 7.0, "accent": "#c0392b", "note": "改变格局"},
    {"name": "重要", "min": 5.0, "accent": "#b7791f", "note": "值得知道"},
    {"name": "值得一看", "min": 3.5, "accent": "#2c5f8a", "note": "有信息量"},
]


def tiers_from(cfg: dict) -> list[dict]:
    raw = cfg.get("tiers") or DEFAULT_TIERS
    out = []
    for tier in raw:
        out.append(
            {
                "name": str(tier.get("name", "")),
                "min": float(tier.get("min", 0)),
                "accent": tier.get("accent", "#666666"),
                "note": tier.get("note", ""),
            }
        )
    out.sort(key=lambda t: t["min"], reverse=True)
    return out


def group_by_tier(items: list[Item], tiers: list[dict]) -> list[tuple[dict, list[Item]]]:
    buckets: list[tuple[dict, list[Item]]] = []
    remaining = sorted(items, key=lambda it: it.score, reverse=True)
    used: set[int] = set()

    for idx, tier in enumerate(tiers):
        upper = tiers[idx - 1]["min"] if idx > 0 else 999
        bucket = [it for it in remaining if tier["min"] <= it.score < upper]
        for it in bucket:
            used.add(id(it))
        if bucket:
            buckets.append((tier, bucket))
    return buckets


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)


def _date_cn(moment: datetime) -> str:
    return f"{moment.month} 月 {moment.day} 日 · {WEEKDAYS[moment.weekday()]}"


def _meta_line(item: Item) -> str:
    parts = [item.source_name, item.time_str]
    if item.category:
        parts.append(item.category)
    if item.also_reported:
        parts.append(f"另 {len(item.also_reported)} 家报道")
    return " · ".join(parts)


def _orig_line(item: Item) -> str:
    """Keep the original headline visible when we translated it."""
    if item.title_zh and item.title_zh != item.title and item.lang != "zh":
        return (
            f'<div style="margin-top:6px;font-size:12px;color:#9a9a9a;line-height:1.5;">'
            f"{_e(item.title)}</div>"
        )
    return ""


def _trim_explain(text: str) -> str:
    """Drop the trailing full stop so '；'.join() does not produce '。；'."""
    return text.strip().rstrip("。．.，,；;")


def _terms_plain(item: Item) -> str:
    parts = [f"{t['term']}（{_trim_explain(t['explain'])}）" for t in item.terms if t.get("term")]
    return "；".join(parts)


def _terms_html(item: Item) -> str:
    if not item.terms:
        return ""
    rows = "；".join(
        f'<span style="color:#4a4a4a;">{_e(t["term"])}</span>'
        f'<span style="color:#8a8a8a;">（{_e(_trim_explain(t["explain"]))}）</span>'
        for t in item.terms
        if t.get("term")
    )
    return (
        f'<div style="margin-top:9px;font-size:13px;line-height:1.75;color:#6b6b6b;">'
        f'<span style="color:#9a9a9a;">名词 </span>{rows}</div>'
    )


def render_html(
    *,
    moment: datetime,
    overview: str,
    grouped: list[tuple[dict, list[Item]]],
    stats: dict,
) -> str:
    total = sum(len(items) for _, items in grouped)

    sections = []
    for idx, (tier, items) in enumerate(grouped):
        accent = tier["accent"]
        header = (
            f'<div id="tier-{idx}" style="padding:26px 26px 8px;">'
            f'<div style="font-size:13px;font-weight:700;color:{accent};letter-spacing:1.5px;">'
            f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
            f'background:{accent};margin-right:8px;vertical-align:middle;"></span>'
            f'{_e(tier["name"])}事件<span style="color:#b0b0b0;font-weight:400;">'
            f" · {len(items)}</span></div></div>"
        )
        blocks = [header]
        for item in items:
            insight_html = ""
            if item.insight:
                insight_html = (
                    f'<div style="margin-top:11px;padding:10px 13px;background:#f7f8f9;'
                    f'border-left:3px solid {accent};font-size:14px;line-height:1.7;color:#4a4a4a;">'
                    f'<span style="color:{accent};font-weight:700;">解读 </span>'
                    f"{_e(item.insight)}</div>"
                )
            summary_html = (
                f'<p style="margin:11px 0 0;font-size:15px;line-height:1.78;color:#333;">'
                f"{_e(item.summary)}</p>"
                if item.summary
                else ""
            )
            reason_html = (
                f'<div style="margin-top:8px;font-size:13px;color:#8a8a8a;">'
                f'重要性 {item.score:.1f}/10 · {_e(item.reason)}</div>'
                if item.reason
                else f'<div style="margin-top:8px;font-size:13px;color:#8a8a8a;">'
                f"重要性 {item.score:.1f}/10</div>"
            )
            blocks.append(
                f'<div style="padding:16px 26px;border-bottom:1px solid #f1f1f1;">'
                f'<a href="{_e(item.url)}" style="font-size:17px;font-weight:600;color:#111;'
                f'text-decoration:none;line-height:1.55;">{_e(item.display_title)}</a>'
                f"{_orig_line(item)}"
                f'<div style="margin-top:7px;font-size:12px;color:#9a9a9a;">{_e(_meta_line(item))}</div>'
                f"{summary_html}{insight_html}{_terms_html(item)}{reason_html}</div>"
            )
        sections.append("".join(blocks))

    overview_html = (
        f'<p style="margin:16px 0 0;font-size:15px;line-height:1.85;color:#333;">{_e(overview)}</p>'
        if overview
        else ""
    )

    body = "".join(sections) or (
        '<div style="padding:40px 26px;text-align:center;color:#999;font-size:15px;">'
        "今天没有达到质量线的新闻。世界安静，就去过自己的生活。</div>"
    )

    footer = (
        f'<div id="footer" style="padding:20px 26px 28px;border-top:1px solid #eee;font-size:12px;'
        f'color:#a0a0a0;line-height:1.9;">'
        f"来源 {stats.get('feeds_ok', 0)} 个 · 候选 {stats.get('candidates', 0)} 条 · "
        f"入选 {total} 条<br>"
        f"生成于 {moment.strftime('%Y-%m-%d %H:%M')} · "
        f"重要性由 AI 按 News Minimalist 方法评估，仅供参考<br>"
        f"摘要由 AI 生成，请以原文为准。"
        + (f"<br><strong>{_e(stats['note'])}</strong>" if stats.get("note") else "")
        + f"</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>今日要闻 · {moment.strftime('%Y-%m-%d')}</title>
</head>
<body style="margin:0;padding:0;background:#f2f2ef;">
<div style="background:#f2f2ef;padding:26px 12px;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.07);">
    <div style="padding:30px 26px 22px;">
      <div style="font-size:11px;letter-spacing:3px;color:#b5b5b5;font-weight:600;">DAILY BRIEF</div>
      <h1 style="margin:8px 0 0;font-size:25px;line-height:1.35;color:#111;font-weight:700;">{_date_cn(moment)}</h1>
      {overview_html}
    </div>
    {body}
    {footer}
  </div>
  <div style="max-width:640px;margin:14px auto 0;text-align:center;font-size:11px;color:#b8b8b8;">
    由 AI 每日自动生成 · 回复本邮件可反馈误判
  </div>
</div>
</body></html>"""


def render_text(
    *, moment: datetime, overview: str, grouped: list[tuple[dict, list[Item]]], stats: dict
) -> str:
    lines = [f"今日要闻 · {moment.strftime('%Y-%m-%d')}", "=" * 34, ""]
    if overview:
        lines += [overview, ""]
    for tier, items in grouped:
        lines.append(f"—— {tier['name']}（{len(items)}）——")
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item.display_title}")
            if item.title_zh and item.title_zh != item.title:
                lines.append(f"   原文标题：{item.title}")
            lines.append(f"   {_meta_line(item)} | {item.score:.1f}分")
            if item.summary:
                lines.append(f"   {item.summary}")
            if item.insight:
                lines.append(f"   解读：{item.insight}")
            if item.terms:
                lines.append(f"   名词：{_terms_plain(item)}")
            lines.append(f"   {item.url}")
            lines.append("")
    lines.append(
        f"来源 {stats.get('feeds_ok', 0)} 个 · 候选 {stats.get('candidates', 0)} 条"
        f" · 生成于 {moment.strftime('%Y-%m-%d %H:%M')}"
    )
    return "\n".join(lines)


# ----------------------------------------------------------- News Minimalist
#
# The NM feed only carries a score, a headline, a source and the article URL;
# the summary text comes from the per-story page. These renderers therefore
# take ``Story``-like objects (duck typed on the attributes below).

NM_TIERS = [
    {"name": "最重大", "min": 6.0, "accent": "#c0392b", "note": "今天最该知道的事"},
    {"name": "重要", "min": 5.5, "accent": "#b7791f", "note": "值得花两分钟"},
    {"name": "值得一看", "min": 5.0, "accent": "#2c5f8a", "note": "信息量够"},
]


def nm_tiers_from(cfg: dict) -> list[dict]:
    raw = cfg.get("tiers") or NM_TIERS
    tiers = [
        {
            "name": str(t.get("name", "")),
            "min": float(t.get("min", 0)),
            "accent": t.get("accent", "#666666"),
            "note": t.get("note", ""),
        }
        for t in raw
    ]
    tiers.sort(key=lambda t: t["min"], reverse=True)
    return tiers


def nm_group(stories: list, tiers: list[dict]) -> list[tuple[dict, list]]:
    buckets: list[tuple[dict, list]] = []
    for idx, tier in enumerate(tiers):
        upper = tiers[idx - 1]["min"] if idx > 0 else 999
        bucket = [s for s in stories if tier["min"] <= s.score < upper]
        if bucket:
            buckets.append((tier, bucket))
    return buckets


def _nm_meta(story) -> str:
    parts = [story.domain or "来源"]
    if story.related:
        parts.append(f"另 {story.related} 家")
    if story.age:
        parts.append(story.age)
    return " · ".join(parts)


def render_nm_html(
    *, moment: datetime, day_line: str, grouped: list[tuple[dict, list]], stats: dict
) -> str:
    total = sum(len(items) for _, items in grouped)

    sections = []
    for idx, (tier, items) in enumerate(grouped):
        accent = tier["accent"]
        header = (
            f'<div id="tier-{idx}" style="padding:26px 26px 8px;">'
            f'<div style="font-size:13px;font-weight:700;color:{accent};letter-spacing:1.5px;">'
            f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
            f'background:{accent};margin-right:8px;vertical-align:middle;"></span>'
            f'{_e(tier["name"])}<span style="color:#b0b0b0;font-weight:400;">'
            f" · {len(items)}</span></div></div>"
        )
        blocks = [header]
        for story in items:
            paras = "".join(
                f'<p style="margin:10px 0 0;font-size:15px;line-height:1.78;color:#333;">{_e(p)}</p>'
                for p in (story.paragraphs or [])
            )
            links = (
                f'<div style="margin-top:10px;font-size:12px;color:#9a9a9a;">'
                f'<a href="{_e(story.source_url)}" style="color:#2c5f8a;text-decoration:none;">原文</a>'
                + (
                    f' · <a href="{_e(story.nm_url)}" style="color:#9a9a9a;text-decoration:none;">'
                    f"News Minimalist 页面</a>"
                    if story.nm_url
                    else ""
                )
                + "</div>"
            )
            blocks.append(
                f'<div style="padding:16px 26px;border-bottom:1px solid #f1f1f1;">'
                f'<div style="font-size:12px;color:{accent};font-weight:700;letter-spacing:0.5px;">'
                f'重要性 {story.score:.1f}/10</div>'
                f'<a href="{_e(story.source_url)}" style="display:block;margin-top:5px;font-size:17px;'
                f'font-weight:600;color:#111;text-decoration:none;line-height:1.55;">{_e(story.title)}</a>'
                f'<div style="margin-top:7px;font-size:12px;color:#9a9a9a;">{_e(_nm_meta(story))}</div>'
                f"{paras}{links}</div>"
            )
        sections.append("".join(blocks))

    body = "".join(sections) or (
        '<div style="padding:40px 26px;text-align:center;color:#999;font-size:15px;">'
        "今天没有达到 5.0 分的新闻。世界安静，就去过自己的生活。</div>"
    )

    footer = (
        f'<div id="footer" style="padding:20px 26px 28px;border-top:1px solid #eee;font-size:12px;'
        f'color:#a0a0a0;line-height:1.9;">'
        f"{_e(stats.get('list_note', ''))}<br>"
        f"入选 {total} 条 · 生成于 {moment.strftime('%Y-%m-%d %H:%M')}<br>"
        f"评分与摘要由 News Minimalist 生成，此处仅转载摘要并附原文链接。"
        f"</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>今日要闻 · {moment.strftime('%Y-%m-%d')}</title>
</head>
<body style="margin:0;padding:0;background:#f2f2ef;">
<div style="background:#f2f2ef;padding:26px 12px;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.07);">
    <div style="padding:30px 26px 22px;">
      <div style="font-size:11px;letter-spacing:3px;color:#b5b5b5;font-weight:600;">DAILY BRIEF</div>
      <h1 style="margin:8px 0 0;font-size:25px;line-height:1.35;color:#111;font-weight:700;">{_date_cn(moment)}</h1>
      <p style="margin:14px 0 0;font-size:15px;line-height:1.8;color:#333;">{_e(day_line)}</p>
    </div>
    {body}
    {footer}
  </div>
  <div style="max-width:640px;margin:14px auto 0;text-align:center;font-size:11px;color:#b8b8b8;">
    每日 07:00 自动整理 · 数据来自 newsminimalist.com
  </div>
</div>
</body></html>"""


def render_nm_text(
    *, moment: datetime, day_line: str, grouped: list[tuple[dict, list]], stats: dict
) -> str:
    lines = [f"今日要闻 · {moment.strftime('%Y-%m-%d')}", "=" * 34, "", day_line, ""]
    for tier, items in grouped:
        lines.append(f"—— {tier['name']}（{len(items)}）——")
        for i, story in enumerate(items, 1):
            lines.append(f"{i}. {story.title}")
            lines.append(f"   {_nm_meta(story)} · 重要性 {story.score:.1f}/10")
            for para in story.paragraphs or []:
                lines.append(f"   {para}")
            lines.append(f"   原文 {story.source_url}")
            lines.append("")
    lines.append(stats.get("list_note", ""))
    lines.append(f"生成于 {moment.strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def render_nm_bark(
    *, moment: datetime, day_line: str, grouped: list[tuple[dict, list]]
) -> tuple[str, str]:
    title = f"今日要闻 · {moment.strftime('%m-%d')}"
    top = [story for _, items in grouped for story in items][:8]
    lines = []
    if day_line:
        lines += [day_line, ""]
    for i, story in enumerate(top, 1):
        lines.append(f"{i}. {story.title}（{story.domain or '来源'}，{story.score:.1f}）")
    if not top:
        lines.append("今天没有达到 5.0 分的新闻。")
    total = sum(len(items) for _, items in grouped)
    lines += ["", f"共 {total} 条 · 完整版见邮箱"]
    body = "\n".join(lines)
    if len(body.encode("utf-8")) > 3900:
        body = body.encode("utf-8")[:3600].decode("utf-8", "ignore").rstrip() + "\n…（详见邮件）"
    return title, body


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>])")


def _md_escape(text: str) -> str:
    """Escape the few characters that actually break Bark's markdown renderer."""
    return _MD_SPECIAL.sub(r"\\\1", text)


def _bark_block_md(item: Item, index: int) -> str:
    """One story as Bark markdown: heading, meta chip, summary, quote, terms, link."""
    score = f"{item.score:.1f}"
    meta = f"`{score}` · {item.source_name}"
    if item.category:
        meta += f" · {item.category}"

    lines = [f"### {index}. {_md_escape(item.display_title)}", meta, ""]
    if item.summary:
        lines.append(_md_escape(item.summary))
        lines.append("")
    if item.insight:
        lines.append(f"> **解读** {_md_escape(item.insight)}")
        lines.append("")
    if item.terms:
        terms = "；".join(
            f"**{_md_escape(t.get('term', ''))}** {_md_escape(_trim_explain(t.get('explain', '')))}"
            for t in item.terms
        )
        lines.append(f"**名词**　{terms}")
        lines.append("")
    lines.append(f"[读原文 →]({item.url})")
    return "\n".join(lines).rstrip()


def _bark_block_med(item: Item, index: int) -> str:
    """Mid-tier block: headline, meta, first sentence of the summary, link."""
    score = f"{item.score:.1f}"
    meta = f"`{score}` · {item.source_name}"
    first = (item.summary or "").strip()
    if len(first) > 120:
        cut = max(first.rfind(ch, 0, 120) for ch in "。！？")
        first = first[: cut + 1] if cut > 40 else first[:120] + "…"
    lines = [f"### {index}. {_md_escape(item.display_title)}", meta, ""]
    if first:
        lines.append(_md_escape(first))
        lines.append("")
    lines.append(f"[读原文 →]({item.url})")
    return "\n".join(lines).rstrip()


def _bark_block(item: Item, index: int) -> str:
    """Plain-text fallback for Bark clients that do not render markdown."""
    head = f"{index}. {item.display_title}（{item.score:.1f} · {item.source_name}）"
    lines = [head]
    if item.summary:
        lines.append(item.summary)
    if item.insight:
        lines.append(f"解读：{item.insight}")
    if item.terms:
        lines.append(f"名词：{_terms_plain(item)}")
    lines.append(f"原文：{item.url}")
    return "\n".join(lines)


def _md_to_plain(md: str) -> str:
    """Rough markdown → plain text, for Bark clients without markdown support."""
    out = re.sub(r"^###\s*", "", md, flags=re.M)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1：\2", out)
    out = out.replace("**", "").replace("`", "")
    out = re.sub(r"^>\s*", "", out, flags=re.M)
    out = re.sub(r"^---\s*$", "—" * 12, out, flags=re.M)
    return out


def _bark_compact(item: Item, index: int) -> str:
    return f"{index}. {_md_escape(item.display_title)} `{item.score:.1f}`"


def render_bark_digest(
    *,
    moment: datetime,
    overview: str,
    grouped: list[tuple[dict, list[Item]]],
    max_bytes: int = 3400,
) -> tuple[str, str, str]:
    """One notification, importance-ordered, that fits Bark's 4KB payload.

    Every story keeps a numbered line so the reader sees the full ranking, and
    the budget left over is spent upgrading the top stories from a headline to
    a full block (summary + insight + terms + link). If the ranking alone does
    not fit, the tail is folded into a "另有 N 条见邮件" line instead of being
    silently dropped.
    """
    items: list[Item] = [it for _, group in grouped for it in group]
    total = len(items)

    if not items:
        title = f"今日要闻 · {moment.strftime('%m-%d')}"
        body = "今天没有达到质量线的新闻。"
        return title, body, body

    head = f"**今日要览**\n\n{_md_escape(overview)}" if overview else ""
    used = len(head.encode("utf-8")) + 8 if head else 0
    budget = max_bytes - used

    # 1) Reserve one compact line per story so the ranking is never truncated.
    compact: list[str] = [_bark_compact(it, i) for i, it in enumerate(items, 1)]
    compact_cost = sum(len(c.encode("utf-8")) + 6 for c in compact)

    kept = total
    while kept > 1 and compact_cost > budget:
        kept -= 1
        compact_cost -= len(compact[kept].encode("utf-8")) + 6

    budget_left = budget - compact_cost

    # 2) Spend what is left upgrading from the most important story downwards.
    blocks: list[str] = []
    upgraded = 0
    for i, item in enumerate(items[:kept], 1):
        base = len(compact[i - 1].encode("utf-8")) + 6
        full = _bark_block_md(item, i)
        delta_full = len(full.encode("utf-8")) - base
        if delta_full <= budget_left:
            blocks.append(full)
            budget_left -= delta_full
            upgraded = i
            continue
        # Second pass: a lighter block (headline + one-line summary + link) is
        # worth more to the reader than another bare headline.
        med = _bark_block_med(item, i)
        delta_med = len(med.encode("utf-8")) - base
        if delta_med <= budget_left:
            blocks.append(med)
            budget_left -= delta_med
            upgraded = i
            continue
        break

    body_parts: list[str] = []
    if head:
        body_parts.append(head)
    if upgraded:
        body_parts.append("\n\n---\n\n".join(blocks))
    rest = [compact[i] for i in range(upgraded, kept)]
    if rest:
        body_parts.append("**其余要闻**\n\n" + "\n".join(rest))
    if kept < total:
        body_parts.append(f"另有 {total - kept} 条见邮件完整版")

    md = "\n\n---\n\n".join(p for p in body_parts if p)
    title = f"今日要闻 · {moment.strftime('%m-%d')} · {total} 条"
    return title, md, _md_to_plain(md)


def render_bark_parts(
    *,
    moment: datetime,
    overview: str,
    grouped: list[tuple[dict, list[Item]]],
    max_bytes: int = 3000,
) -> list[tuple[str, str, str]]:
    """Split the full digest into as many Bark pushes as the 4KB APNs limit needs.

    Returns (title, markdown, plain) triples. iOS caps one notification payload
    at 4KB, which is only ~1100 Chinese characters, so a complete 15-item brief
    cannot fit in a single push. We emit several notifications in the same
    group; they stack in the lock screen, and only the first one makes a sound.
    """
    items: list[Item] = [it for _, group in grouped for it in group]
    total = len(items)

    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            chunks.append(current)
            current, size = [], 0

    if overview:
        current.append(f"**今日要览**\n\n{_md_escape(overview)}")
        size = len(overview.encode("utf-8")) + 20

    if not items:
        current.append("今天没有达到质量线的新闻。")
        flush()
    else:
        for i, item in enumerate(items, 1):
            block = _bark_block_md(item, i)
            bsize = len(block.encode("utf-8")) + 8
            if current and size + bsize > max_bytes:
                flush()
            current.append(block)
            size += bsize
        flush()

    n = len(chunks)
    parts: list[tuple[str, str, str]] = []
    for idx, blocks in enumerate(chunks, 1):
        if n == 1:
            title = f"今日要闻 · {moment.strftime('%m-%d')} · {total} 条"
        else:
            title = f"今日要闻 {idx}/{n} · {moment.strftime('%m-%d')} · {total} 条"
        md = "\n\n---\n\n".join(blocks)

        plain_bits: list[str] = []
        for block in blocks:
            plain_bits.append(re.sub(r"^###\s*", "", block, flags=re.M))
        plain = "\n\n".join(plain_bits)
        plain = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1：\2", plain)
        plain = plain.replace("**", "").replace("`", "").replace("> ", "")
        parts.append((title, md, plain))
    return parts


def render_bark(
    *, moment: datetime, overview: str, grouped: list[tuple[dict, list[Item]]]
) -> tuple[str, str]:
    """Backwards-compatible single-message version (first part only)."""
    parts = render_bark_parts(moment=moment, overview=overview, grouped=grouped)
    return parts[0][:2] if parts else (f"今日要闻 · {moment.strftime('%m-%d')}", "")

