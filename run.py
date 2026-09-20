# -*- coding: utf-8 -*-
"""PyInstaller 打包入口：等价于 python -m qoder2api.app"""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # console=False 打包后 sys.stdout/stderr 为 None，print/logging 会崩；
    # 统一重定向到 exe 同目录日志文件。
    base = Path(sys.executable).resolve().parent
    log_file = open(base / "qodergateway.log", "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = log_file
    sys.stderr = log_file

from qoder2api.app import main

if __name__ == "__main__":
    main()
