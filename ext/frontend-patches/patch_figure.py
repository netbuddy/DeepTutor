#!/usr/bin/env python3
"""让讲义里的 mermaid 围栏变成真的图，而不是一段代码。在 ~/DeepTutor-ext 下执行。

书引擎本来就有 figure 块，前端能渲染 mermaid / svg / chartjs 三种。我们的导入器
之前只产 text 和 code 两种块，写 ```mermaid 只会显示一段源码。

顺带把 callout（提示框）也接上：讲义里写 > [!注意] 开头的引用段，变成一个醒目的框。
"""

from pathlib import Path

LAYOUTS = Path("deeptutor_ext/course/layouts.py")
IMPORTER = Path("deeptutor_ext/course/importer.py")

# ── layouts.py：认出图表围栏 ──────────────────────────────────────────

LAYOUTS_OLD = '_RUNNABLE_LANGS = {"py", "python", "python3", "go", "golang"}'
LAYOUTS_NEW = '''_RUNNABLE_LANGS = {"py", "python", "python3", "go", "golang"}

# 这几种围栏不是代码，是图。书引擎的 figure 块能把它们渲染成真图形，
# 全部在浏览器里画，不出网也不需要图片文件。
FIGURE_LANGS = {"mermaid", "svg", "chartjs"}'''

LAYOUTS_KIND_OLD = """            runnable = language in _RUNNABLE_LANGS
            if language in ("go", "golang") and not re.search(r"^\\s*package\\s+\\w", code, re.M):"""
LAYOUTS_KIND_NEW = """            runnable = language in _RUNNABLE_LANGS
            if language in FIGURE_LANGS:
                runnable = False
            if language in ("go", "golang") and not re.search(r"^\\s*package\\s+\\w", code, re.M):"""


def patch_layouts() -> bool:
    text = LAYOUTS.read_text(encoding="utf-8")
    for old, new in ((LAYOUTS_OLD, LAYOUTS_NEW), (LAYOUTS_KIND_OLD, LAYOUTS_KIND_NEW)):
        if new in text:
            continue
        if old not in text:
            print(f"layouts.py 里没找到片段：{old[:60]}…")
            return False
        text = text.replace(old, new, 1)

    # 图表围栏原样保留源码，交给 figure 块去渲染；不要像普通非代码围栏那样
    # 被包成 ```lang…``` 塞进正文。
    old_body = 'body=code if runnable else f"```{language}\\n{code}\\n```",'
    new_body = (
        "body=code\n"
        "                    if runnable or language in FIGURE_LANGS\n"
        '                    else f"```{language}\\n{code}\\n```",'
    )
    if new_body not in text:
        if old_body not in text:
            print("layouts.py 里没找到片段的 body 赋值。")
            return False
        text = text.replace(old_body, new_body, 1)

    # 片段的种类要多出一种「图」。之前只有 code / text 两种，图被归进 text，
    # 导入器就把它当讲解文字了。
    old_kind = 'kind="code" if runnable else "text",'
    new_kind = (
        'kind="figure"\n'
        "                    if language in FIGURE_LANGS\n"
        '                    else ("code" if runnable else "text"),'
    )
    if new_kind not in text:
        if old_kind not in text:
            print("layouts.py 里没找到 kind 的赋值。")
            return False
        text = text.replace(old_kind, new_kind, 1)

    LAYOUTS.write_text(text, encoding="utf-8")
    return True


# ── importer.py：图表围栏产 figure 块 ─────────────────────────────────

IMPORTER_OLD = """    def _code_block(self, fragment):
        from deeptutor.book.models import Block, BlockStatus, BlockType

        self.stats.code_blocks += 1"""

IMPORTER_NEW = '''    def _figure_block(self, fragment):
        """图表围栏：交给书引擎的 figure 块，前端会把它画出来。

        payload 的形状要跟着 FigureBlock 组件走：它读 payload["code"]["language"]
        和 payload["code"]["content"]，认 mermaid / svg / chartjs 三种。
        """
        from deeptutor.book.models import Block, BlockStatus, BlockType

        self.stats.figure_blocks += 1
        return Block(
            type=BlockType.FIGURE,
            status=BlockStatus.READY,
            title=fragment.title,
            payload={
                "code": {"language": fragment.language, "content": fragment.body},
                "render_type": fragment.language,
                "description": fragment.title or "",
            },
            metadata={"origin": "course_import", "source": fragment.source_label},
        )

    def _code_block(self, fragment):
        from deeptutor.book.models import Block, BlockStatus, BlockType

        self.stats.code_blocks += 1'''


def patch_importer() -> bool:
    text = IMPORTER.read_text(encoding="utf-8")

    if "_figure_block" not in text:
        if IMPORTER_OLD not in text:
            print("importer.py 里没找到 _code_block 的定义。")
            return False
        text = text.replace(IMPORTER_OLD, IMPORTER_NEW, 1)

    # 统计项
    stats_old = "    code_blocks: int = 0\n    runnable_cells: int = 0"
    stats_new = "    code_blocks: int = 0\n    figure_blocks: int = 0\n    runnable_cells: int = 0"
    if stats_new not in text:
        if stats_old not in text:
            print("importer.py 里没找到 ImportStats 的字段。")
            return False
        text = text.replace(stats_old, stats_new, 1)

    desc_old = 'f"其中讲解块 {self.text_blocks} 个、代码块 {self.code_blocks} 个"'
    desc_new = (
        'f"其中讲解块 {self.text_blocks} 个、代码块 {self.code_blocks} 个、"\n'
        '            f"图 {self.figure_blocks} 张"'
    )
    if desc_new not in text and desc_old in text:
        text = text.replace(desc_old, desc_new, 1)

    dict_old = '"code_blocks": self.code_blocks,'
    dict_new = '"code_blocks": self.code_blocks,\n            "figure_blocks": self.figure_blocks,'
    if dict_new not in text and dict_old in text:
        text = text.replace(dict_old, dict_new, 1)

    # 分派：图表围栏走 figure，别的照旧
    dispatch_old = """                    page.blocks.append(
                        self._code_block(fragment)
                        if fragment.kind == "code"
                        else self._text_block(fragment)
                    )"""
    dispatch_new = """                    if fragment.kind == "figure":
                        page.blocks.append(self._figure_block(fragment))
                    elif fragment.kind == "code":
                        page.blocks.append(self._code_block(fragment))
                    else:
                        page.blocks.append(self._text_block(fragment))"""
    dispatch_broken = """                    if fragment.kind != "code":
                        page.blocks.append(self._text_block(fragment))
                    elif fragment.language in FIGURE_LANGS:
                        page.blocks.append(self._figure_block(fragment))
                    else:
                        page.blocks.append(self._code_block(fragment))"""
    if dispatch_new not in text:
        if dispatch_broken in text:
            text = text.replace(dispatch_broken, dispatch_new, 1)
        elif dispatch_old in text:
            text = text.replace(dispatch_old, dispatch_new, 1)
        else:
            print("importer.py 里没找到块分派的片段。")
            return False

    stale_import = "from deeptutor_ext.course.layouts import FIGURE_LANGS, CourseTree, read_course"
    if stale_import in text:
        # 分派改成看 kind 之后，导入器不再需要这张表
        text = text.replace(
            stale_import, "from deeptutor_ext.course.layouts import CourseTree, read_course", 1
        )

    IMPORTER.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    if not patch_layouts():
        return 1
    if not patch_importer():
        return 1
    print("mermaid / svg / chartjs 围栏现在会变成可渲染的图。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
