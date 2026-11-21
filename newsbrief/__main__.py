# -*- coding: utf-8 -*-
"""Entry point: dispatch on ``source`` in config.yaml."""

from __future__ import annotations

import sys

from .config import load as load_config


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = "config.yaml"
    for flag in ("-c", "--config"):
        if flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                path = argv[idx + 1]
            break
    try:
        source = str(load_config(path).get("source", "newsminimalist")).lower()
    except Exception:  # noqa: BLE001
        source = "newsminimalist"

    if source in ("nm", "newsminimalist", "news-minimalist"):
        from .nm_main import main as run

        return run(argv)

    from .main import main as run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())

