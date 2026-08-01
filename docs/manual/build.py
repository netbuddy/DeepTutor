#!/usr/bin/env python3
"""把手册模板里的图片占位符换成内嵌图片，生成单文件的 index.html。

手册要能拷给别人、放到任意静态服务上直接打开，所以图片不走外链，
全部以 base64 编在 HTML 里。占位符的写法是 {{IMG:文件名|图说}}。

用法：cd ~/DeepTutor-ext/docs/manual && python3 build.py
"""

from __future__ import annotations

import base64
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
TEMPLATE = HERE / "模板.html"
IMG_DIR = HERE / "img"
OUTPUT = HERE / "index.html"

PLACEHOLDER = re.compile(r"\{\{IMG:([^|]+)\|([^}]+)\}\}")


def main() -> int:
    if not TEMPLATE.exists():
        print(f"找不到模板：{TEMPLATE}", file=sys.stderr)
        return 1

    missing: list[str] = []

    def replace(match: re.Match) -> str:
        name, caption = match.group(1), match.group(2)
        image = IMG_DIR / f"{name}.webp"
        if not image.exists():
            missing.append(name)
            return f"<!-- 缺图 {name} -->"
        encoded = base64.b64encode(image.read_bytes()).decode()
        return (
            "<figure>\n"
            f'  <img src="data:image/webp;base64,{encoded}" alt="{caption}" loading="lazy">\n'
            f"  <figcaption>{caption}</figcaption>\n"
            "</figure>"
        )

    html = PLACEHOLDER.sub(replace, TEMPLATE.read_text(encoding="utf-8"))
    OUTPUT.write_text(html, encoding="utf-8")

    if missing:
        print("以下图片没找到，成品里留了注释占位：" + "、".join(missing), file=sys.stderr)
    print(f"已生成 {OUTPUT.name}：{len(html) / 1024:.0f} KB，内嵌 {html.count('data:image/webp')} 张图")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
