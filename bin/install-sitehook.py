#!/usr/bin/env python3
"""往虚拟环境里放一个 .pth 站点钩子，让扩展在任何入口下都自动接入。

Python 在启动时会执行 site-packages 下 ``*.pth`` 文件里以 ``import`` 开头的行。
我们借这一条机制，让 ``deeptutor`` 命令、uvicorn、后台任务进程等所有入口都不必
改启动方式就带上扩展。

用法：<虚拟环境的 python> bin/install-sitehook.py
重复执行是安全的，内容不变时不会重写。
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

LINE = "import deeptutor_ext._sitehook\n"
FILENAME = "deeptutor_ext.pth"


def site_packages_dir() -> Path:
    for candidate in site.getsitepackages():
        path = Path(candidate)
        if path.name == "site-packages" and path.is_dir():
            return path
    raise SystemExit("找不到这个虚拟环境的 site-packages 目录，无法安装站点钩子。")


def main() -> int:
    target = site_packages_dir() / FILENAME
    if target.exists() and target.read_text(encoding="utf-8") == LINE:
        print(f"站点钩子已就位，无需重复安装：{target}")
        return 0
    target.write_text(LINE, encoding="utf-8")
    print(f"站点钩子已安装：{target}")
    print(f"使用的解释器：{sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
