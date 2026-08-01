#!/usr/bin/env python3
"""把手册模板里的图片占位符换成内嵌图片，生成两份成品。

手册要能拷给别人、放到任意静态服务上直接打开，所以图片不走外链，
全部以 base64 编在 HTML 里。占位符的写法是 {{IMG:文件名|图说}}。

生成两份是有原因的：

* ``index.html`` 是**完整的 HTML 文档**，自带 ``<meta charset="utf-8">``。
  给静态文件服务用的时候必须是这一份——Python 自带的 http.server 返回的
  Content-Type 不带字符集，页面里再没有 charset 声明的话，浏览器会按自己的默认
  编码去解析 UTF-8 字节，整页中文全变乱码。
* ``artifact.html`` 是**页面片段**（没有 doctype / html / head / body）。
  发布成在线页面时用它，那边的平台会自己套一层带 charset 的外壳，
  片段里再写一遍反而多余。

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
FULL_DOC = HERE / "index.html"
FRAGMENT = HERE / "artifact.html"

PLACEHOLDER = re.compile(r"\{\{IMG:([^|]+)\|([^}]+)\}\}")
TITLE = re.compile(r"<title>(.*?)</title>\s*", re.S)


def build_fragment() -> tuple[str, list[str]]:
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

    return PLACEHOLDER.sub(replace, TEMPLATE.read_text(encoding="utf-8")), missing


def wrap_as_document(fragment: str) -> str:
    """把片段套成一份完整文档，标题从片段里抽出来放进 head。"""
    match = TITLE.search(fragment)
    title = match.group(1).strip() if match else "DeepTutor 使用手册"
    body = TITLE.sub("", fragment, count=1) if match else fragment
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{title}</title>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def main() -> int:
    if not TEMPLATE.exists():
        print(f"找不到模板：{TEMPLATE}", file=sys.stderr)
        return 1

    fragment, missing = build_fragment()
    FRAGMENT.write_text(fragment, encoding="utf-8")
    FULL_DOC.write_text(wrap_as_document(fragment), encoding="utf-8")

    if missing:
        print("以下图片没找到，成品里留了注释占位：" + "、".join(missing), file=sys.stderr)
    count = fragment.count("data:image/webp")
    print(f"已生成 index.html（完整文档，带 charset）与 artifact.html（片段），各内嵌 {count} 张图")
    print(f"  index.html   {FULL_DOC.stat().st_size / 1024:.0f} KB")
    print(f"  artifact.html {FRAGMENT.stat().st_size / 1024:.0f} KB")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
