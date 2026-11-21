# -*- coding: utf-8 -*-
"""Delivery: SMTP email + Bark push."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)


def send_email(cfg: dict, *, subject: str, text: str, html: str) -> None:
    host = cfg.get("smtp_host") or "smtp.qq.com"
    port = int(cfg.get("smtp_port") or 465)
    user = cfg.get("username") or cfg.get("from") or ""
    password = cfg.get("password") or ""
    sender = cfg.get("from") or user
    recipients = cfg.get("to") or []
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.replace(";", ",").split(",") if r.strip()]

    if not user or not password:
        raise RuntimeError("邮件配置不完整：需要 smtp_host / username / password")
    if not recipients:
        raise RuntimeError("邮件配置不完整：需要 to")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.get("sender_name") or "每日要闻", sender))
    msg["To"] = ", ".join(recipients)
    msg["Reply-To"] = formataddr((cfg.get("sender_name") or "每日要闻", sender))
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] or None)
    # Keep out-of-office robots from replying and looping back into the filter.
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=45, context=context) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=45) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)

    log.info("邮件已发送 → %s", ", ".join(recipients))


def _bark_endpoint(url: str) -> tuple[str, str]:
    parts = urlsplit(url.strip())
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        raise RuntimeError(f"Bark 地址里没有 device key: {url}")
    key = segments[-1]
    return f"{parts.scheme}://{parts.netloc}/push", key


def send_bark(
    cfg: dict,
    *,
    title: str,
    body: str,
    markdown: str | None = None,
    sound: str | None = None,
    level: str | None = None,
) -> None:
    endpoint, key = _bark_endpoint(cfg.get("url") or "")
    payload = {
        "device_key": key,
        "title": title,
        "body": body,
        "group": cfg.get("group", "每日要闻"),
        "sound": sound if sound is not None else cfg.get("sound", "bell"),
        "isArchive": 1,
    }
    # The 4KB APNs budget has to cover body + markdown + the other fields, so
    # when we send markdown the plain body is only kept as a short fallback for
    # Bark clients that cannot render it.
    if markdown:
        payload["markdown"] = markdown
        if len(body.encode("utf-8")) > 320:
            payload["body"] = body.encode("utf-8")[:300].decode("utf-8", "ignore") + "…"
    if level:
        payload["level"] = level
    if cfg.get("icon"):
        payload["icon"] = cfg["icon"]
    if cfg.get("link"):
        payload["url"] = cfg["link"]

    resp = requests.post(endpoint, json=payload, timeout=25)
    if resp.status_code != 200:
        raise RuntimeError(f"Bark 返回 {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("code") != 200:
        raise RuntimeError(f"Bark 返回异常: {data}")
    log.info("Bark 推送成功（%s，%d 字节）", title, len(body.encode("utf-8")))
