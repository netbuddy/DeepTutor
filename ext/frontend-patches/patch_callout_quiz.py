#!/usr/bin/env python3
"""让讲义能写提示框和自测题。在 ~/DeepTutor-ext 下执行。

书引擎有 callout 块（四种样式：要点、坑、小结、提示）和 quiz 块（选择题，
能作答、能看解析）。导入器之前只产 text / code / figure，这两种用不上。

讲义里的写法：

    > [!要点]
    > 主循环有两个出口，不是一个。

    > [!坑]
    > 值接收者上的 append 改的是拷贝，编译器不会拦你。

自测题用一个 quiz 围栏，里面是 YAML：

    ```quiz
    - 题目: 主循环为什么必须有预算？
      选项:
        A: 省钱
        B: 模型可能陷入循环，而且不报错
        C: 让回答更快
      答案: B
      解析: 模型陷入循环时不抛异常也不崩，只是永远不结束。
    ```
"""

from pathlib import Path

LAYOUTS = Path("deeptutor_ext/course/layouts.py")
IMPORTER = Path("deeptutor_ext/course/importer.py")

# ── layouts.py ───────────────────────────────────────────────────────

LANGS_OLD = 'FIGURE_LANGS = {"mermaid", "svg", "chartjs"}'
LANGS_NEW = '''FIGURE_LANGS = {"mermaid", "svg", "chartjs"}

# 自测题围栏。内容是 YAML，一题一项。
QUIZ_LANGS = {"quiz"}

# 提示框：引用段落以 > [!要点] 这类标记开头。四种样式对应书引擎的四种 callout。
CALLOUT_KINDS = {
    "要点": "key_idea",
    "坑": "common_pitfall",
    "小结": "summary",
    "提示": "tip",
    "key_idea": "key_idea",
    "common_pitfall": "common_pitfall",
    "summary": "summary",
    "tip": "tip",
}

_CALLOUT_RE = re.compile(r"^>\\s*\\[!([^\\]]+)\\]\\s*\\n((?:>.*\\n?)*)", re.M)


def _split_callouts(text: str, label: str) -> list["Fragment"]:
    """把一段正文按提示框标记切开：标记内的成 callout，标记外的仍是讲解。"""
    out: list[Fragment] = []
    cursor = 0
    for match in _CALLOUT_RE.finditer(text):
        before = text[cursor : match.start()].strip()
        if before:
            out += _fragments_from_markdown(before, label)
        kind = CALLOUT_KINDS.get(match.group(1).strip())
        body = "\\n".join(
            line.lstrip(">").strip() for line in match.group(2).splitlines()
        ).strip()
        if kind and body:
            out.append(
                Fragment(
                    kind="callout",
                    body=body,
                    title=match.group(1).strip(),
                    language=kind,
                    runnable=False,
                    cwd="",
                    cell_index=0,
                    source_label=label,
                )
            )
        elif body:
            # 不认识的标记按普通引用处理，不要把内容吞掉
            out += _fragments_from_markdown(match.group(0), label)
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        out += _fragments_from_markdown(tail, label)
    return out'''

# 讲解片段改走 _split_callouts
PROSE_CALLS = [
    ("            fragments += _fragments_from_markdown(prose, label)",
     "            fragments += _split_callouts(prose, label)"),
    ("        fragments += _fragments_from_markdown(tail, label)",
     "        fragments += _split_callouts(tail, label)"),
]

KIND_OLD = '''kind="figure"
                    if language in FIGURE_LANGS
                    else ("code" if runnable else "text"),'''
KIND_NEW = '''kind=_fence_kind(language, runnable),'''

FENCE_KIND_FN = '''def _fence_kind(language: str, runnable: bool) -> str:
    """一个围栏该变成哪种片段。"""
    if language in FIGURE_LANGS:
        return "figure"
    if language in QUIZ_LANGS:
        return "quiz"
    return "code" if runnable else "text"


def _split_prose_and_code('''

BODY_OLD = '''body=code
                    if runnable or language in FIGURE_LANGS
                    else f"```{language}\\n{code}\\n```",'''
BODY_NEW = '''body=code
                    if runnable or language in FIGURE_LANGS or language in QUIZ_LANGS
                    else f"```{language}\\n{code}\\n```",'''


# ── importer.py ──────────────────────────────────────────────────────

IMPORTER_BLOCKS = '''    def _callout_block(self, fragment):
        """提示框。fragment.language 已经是书引擎认的那四种样式之一。"""
        from deeptutor.book.models import Block, BlockStatus, BlockType

        self.stats.callout_blocks += 1
        return Block(
            type=BlockType.CALLOUT,
            status=BlockStatus.READY,
            title=fragment.title,
            payload={
                "variant": fragment.language,
                "markdown": fragment.body,
                "text": fragment.body,
            },
            metadata={"origin": "course_import", "source": fragment.source_label},
        )

    def _quiz_block(self, fragment):
        """自测题。围栏里是 YAML，一题一项。

        解析失败不能让整门课导不进来——退化成一段普通的讲解文字，
        并在日志里说明是哪一段有问题。
        """
        from deeptutor.book.models import Block, BlockStatus, BlockType

        try:
            import yaml

            items = yaml.safe_load(fragment.body) or []
        except Exception as exc:
            logger.warning("自测题解析失败（%s）：%s", fragment.source_label, exc)
            return self._text_block(fragment)

        questions = []
        for i, item in enumerate(items if isinstance(items, list) else [], start=1):
            if not isinstance(item, dict):
                continue
            options = item.get("选项") or item.get("options") or {}
            questions.append(
                {
                    "question_id": f"q{i}",
                    "question": str(item.get("题目") or item.get("question") or ""),
                    "question_type": "single_choice" if options else "short_answer",
                    "options": {str(k): str(v) for k, v in options.items()} or None,
                    "correct_answer": str(item.get("答案") or item.get("answer") or ""),
                    "explanation": str(item.get("解析") or item.get("explanation") or ""),
                }
            )
        if not questions:
            return self._text_block(fragment)

        self.stats.quiz_blocks += 1
        return Block(
            type=BlockType.QUIZ,
            status=BlockStatus.READY,
            title=fragment.title or "随堂自测",
            payload={"questions": questions},
            metadata={"origin": "course_import", "source": fragment.source_label},
        )

    def _figure_block(self, fragment):'''

DISPATCH_OLD = """                    if fragment.kind == "figure":
                        page.blocks.append(self._figure_block(fragment))
                    elif fragment.kind == "code":
                        page.blocks.append(self._code_block(fragment))
                    else:
                        page.blocks.append(self._text_block(fragment))"""
DISPATCH_NEW = """                    builder = {
                        "figure": self._figure_block,
                        "quiz": self._quiz_block,
                        "callout": self._callout_block,
                        "code": self._code_block,
                    }.get(fragment.kind, self._text_block)
                    page.blocks.append(builder(fragment))"""

STATS_OLD = "    figure_blocks: int = 0"
STATS_NEW = "    figure_blocks: int = 0\n    callout_blocks: int = 0\n    quiz_blocks: int = 0"

DICT_OLD = '"figure_blocks": self.figure_blocks,'
DICT_NEW = ('"figure_blocks": self.figure_blocks,\n'
            '            "callout_blocks": self.callout_blocks,\n'
            '            "quiz_blocks": self.quiz_blocks,')


def patch(path: Path, pairs, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in text:
            continue
        if old not in text:
            print(f"{label} 里没找到片段：{old[:70]}…")
            return False
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    ok = patch(
        LAYOUTS,
        [(LANGS_OLD, LANGS_NEW), (KIND_OLD, KIND_NEW), (BODY_OLD, BODY_NEW),
         ("def _split_prose_and_code(", FENCE_KIND_FN)] + PROSE_CALLS,
        "layouts.py",
    )
    if not ok:
        return 1

    ok = patch(
        IMPORTER,
        [("    def _figure_block(self, fragment):", IMPORTER_BLOCKS),
         (DISPATCH_OLD, DISPATCH_NEW), (STATS_OLD, STATS_NEW), (DICT_OLD, DICT_NEW)],
        "importer.py",
    )
    if not ok:
        return 1

    print("提示框与自测题的通道已打通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
