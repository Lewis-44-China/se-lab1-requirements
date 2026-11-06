#!/usr/bin/env python3
"""程序入口：python3 main.py"""

# 第二轮审查（2026-11-05）：入口只转调 CLI main；参数解析、建库、seed 与
# 登录循环都在 ticketing.presentation_表现层.cli，职责清晰，复核无误。

from ticketing.presentation_表现层.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
