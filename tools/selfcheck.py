# -*- coding: utf-8 -*-
"""Fast offline checks for the pieces that are easy to get subtly wrong.

No network, no API key, no files written. Run: python tools/selfcheck.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from newsbrief.cluster import cluster, jaccard, tokens  # noqa: E402
from newsbrief.fetch import clean_text, norm_url  # noqa: E402
from newsbrief.llm import _tolerant_json  # noqa: E402
from newsbrief.models import Item  # noqa: E402
from newsbrief.rank import drop_echo_summaries  # noqa: E402
from newsbrief.render import DEFAULT_TIERS, group_by_tier, render_bark  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    print(("  ok   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED += 1


def item(title: str, lead: str = "", source: str = "S", weight: float = 1.0) -> Item:
    return Item(
        uid=title[:16],
        title=title,
        url="https://example.com/" + str(abs(hash(title)) % 9999),
        source_id=source,
        source_name=source,
        published=datetime.now(timezone.utc),
        lead=lead,
        weight=weight,
    )


def test_json_repair() -> None:
    print("JSON 容错")
    good = _tolerant_json('{"items":[{"id":1,"score":7}]}')
    check("正常 JSON", good["items"][0]["score"] == 7)
    fenced = _tolerant_json('```json\n{"items": [{"id": 1,},]}\n```')
    check("代码块 + 尾逗号", fenced["items"][0]["id"] == 1)
    bare = _tolerant_json('[{"id":1}]')
    check("顶层数组包装成 items", bare["items"][0]["id"] == 1)
    chatty = _tolerant_json('好的，结果如下：\n{"items":[{"id":2}]}\n希望有帮助')
    check("前后夹杂说明文字", chatty["items"][0]["id"] == 2)


def test_clean_text() -> None:
    print("文本清洗")
    raw = "<p>他说&ldquo;不&rdquo;，然后&nbsp;走了</p>"
    out = clean_text(raw)
    check("去标签 + 反转义 + 直引号", out == '他说"不"，然后 走了', out)
    check("弯引号已归一", clean_text("it\u2019s a test") == "it's a test")
    check("长度截断", len(clean_text("啊" * 900, 100)) == 100)


def test_norm_url() -> None:
    print("URL 归一")
    a = norm_url("https://example.com/a/?utm_source=x&id=7#top")
    b = norm_url("https://example.com/a?id=7")
    check("去掉 utm 与锚点后一致", a == b, f"{a} vs {b}")
    check("保留非跟踪参数", "id=7" in a)


def test_cluster() -> None:
    print("同题聚合")
    check("明显不同", jaccard(tokens("苹果发布新款手机"), tokens("欧洲议会通过法案")) < 0.1)
    check(
        "高度相似",
        jaccard(tokens("美联储宣布降息25个基点"), tokens("美联储宣布降息 25 个基点")) > 0.6,
    )
    a = item("美联储宣布降息25个基点", weight=0.8, source="A")
    b = item("美联储宣布降息 25 个基点", weight=1.2, source="B")
    c = item("欧洲议会通过人工智能法案", source="C")
    merged = cluster([a, b, c], threshold=0.45)
    check("同题合并成 2 条", len(merged) == 2, str(len(merged)))
    rep = [m for m in merged if "降息" in m.title][0]
    check("代表取权重更高的源", rep.source_name == "B", rep.source_name)
    check("记录了另 1 家报道", rep.also_reported == ["A"], str(rep.also_reported))


def test_tiers() -> None:
    print("分档")
    items = []
    for score in (9.0, 7.0, 5.0, 4.0, 3.5, 3.4):
        it = item(f"样例{score}")
        it.score = score
        items.append(it)
    grouped = group_by_tier(items, DEFAULT_TIERS)
    check("分三档", len(grouped) == 3, str([len(g[1]) for g in grouped]))
    check("低于最低档的丢掉", sum(len(g[1]) for g in grouped) == 5)
    check("档内按分数降序", grouped[0][1][0].score == 9.0)


def test_echo_drop() -> None:
    print("摘要复读检测")
    echo = item("美联储宣布降息25个基点")
    echo.summary = "美联储宣布降息 25 个基点。这是今年第二次降息。"
    real = item("美联储宣布降息25个基点")
    real.summary = "这是今年第二次降息，基准利率降至 3.75%–4.00% 区间。"
    drop_echo_summaries([echo, real])
    check("复读标题的摘要被清空", echo.summary == "", echo.summary)
    check("补充了新信息的摘要保留", real.summary != "")


def test_bark_limit() -> None:
    print("Bark 长度")
    it = item("标题" * 60)
    it.score = 8.0
    it.also_reported = []
    title, body = render_bark(moment=datetime.now(timezone.utc), overview="总览" * 30, grouped=[(DEFAULT_TIERS[0], [it])])
    check("标题不超 32 字", len(title) <= 32, title)
    check("正文不超 3900 字节", len(body.encode("utf-8")) <= 3900, str(len(body.encode("utf-8"))))


def test_delivery() -> None:
    print("推送构造（用假对象，不真发）")
    from newsbrief import deliver

    captured: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            captured["host"] = host
            captured["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            captured["login"] = (user, password)

        def send_message(self, msg):
            captured["msg"] = msg

    real_smtp = deliver.smtplib.SMTP_SSL
    deliver.smtplib.SMTP_SSL = FakeSMTP  # type: ignore[assignment]
    try:
        deliver.send_email(
            {
                "smtp_host": "smtp.qq.com",
                "smtp_port": 465,
                "username": "me@qq.com",
                "password": "authcode",
                "from": "me@qq.com",
                "to": "you@example.com; second@example.com",
                "sender_name": "每日要闻",
            },
            subject="今日要闻 · 11-21",
            text="纯文本版本",
            html="<b>HTML 版本</b>",
        )
    finally:
        deliver.smtplib.SMTP_SSL = real_smtp  # type: ignore[assignment]

    msg = captured.get("msg")
    check("走 465 SSL 端口", captured.get("port") == 465, str(captured.get("port")))
    check("登录用了授权码", captured.get("login") == ("me@qq.com", "authcode"))
    check("收件人按 ; 拆分", msg is not None and len(msg["To"].split(",")) == 2, msg and msg["To"])
    check("同时带纯文本和 HTML", msg is not None and msg.is_multipart(), str(type(msg)))
    if msg is not None:
        parts = [p.get_content_type() for p in msg.walk()]
        check("包含 text/plain 与 text/html", "text/plain" in parts and "text/html" in parts, str(parts))
        html_part = [p for p in msg.walk() if p.get_content_type() == "text/html"][0]
        check("HTML 内容可解码", "<b>HTML 版本</b>" in html_part.get_content())

    calls: dict = {}

    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"code": 200, "message": "success"}

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["json"] = json or {}
        return FakeResp()

    real_post = deliver.requests.post
    deliver.requests.post = fake_post  # type: ignore[assignment]
    try:
        deliver.send_bark(
            {"url": "https://api.day.app/AbCdEf123/", "group": "每日要闻", "sound": "bell"},
            title="今日要闻 · 11-21",
            body="正文",
        )
    finally:
        deliver.requests.post = real_post  # type: ignore[assignment]

    check("推送地址归一为 /push", calls.get("url") == "https://api.day.app/push", str(calls.get("url")))
    check("device_key 取自原地址末段", calls.get("json", {}).get("device_key") == "AbCdEf123")
    check("正文原样传给 Bark", calls.get("json", {}).get("body") == "正文")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    for fn in (
        test_json_repair,
        test_clean_text,
        test_norm_url,
        test_cluster,
        test_tiers,
        test_echo_drop,
        test_bark_limit,
        test_delivery,
    ):
        fn()
    print()
    if FAILED:
        print(f"{FAILED} 项未通过")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
