"""读 .ipynb 文件，把它拆成一格一格，顺便把已存的输出整理成可展示的形式。

notebook 文件本质是一份 JSON，里面混着源码、讲解文字，以及上一次运行留下的输出。
输出里的图片是 base64 长字符串，一份典型的课程 notebook 有七成体积是它——直接原样
搬进页面既撑大文件，检索时也全是噪声。所以这里只保留三样东西：讲解、源码、
以及输出的纯文本形式（截断），图片一律换成一句占位说明，学生点运行按钮就能重新生成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

# 单格已存输出保留的文本上限。超过的部分学生重新运行就能看到完整版。
_MAX_SAVED_OUTPUT_CHARS = 1200


@dataclass
class NotebookCell:
    index: int  # 从 1 开始，与界面上显示的编号一致
    kind: str  # "code" 或 "markdown"
    source: str
    language: str = "python"
    saved_output: str = ""  # 上一次运行留下的文本输出
    saved_image_count: int = 0


@dataclass
class ParsedNotebook:
    path: Path
    cells: list[NotebookCell] = field(default_factory=list)

    @property
    def cwd(self) -> str:
        """执行时的工作目录。课程代码用相对路径读数据，必须切到 notebook 所在目录。"""
        return str(self.path.parent)

    @property
    def code_cells(self) -> list[NotebookCell]:
        return [c for c in self.cells if c.kind == "code"]


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return str(value or "")


def _saved_output(outputs: list[dict[str, Any]]) -> tuple[str, int]:
    """把已存输出压成一段文本，并数一数里面有几张图。"""
    chunks: list[str] = []
    images = 0
    for output in outputs:
        data = output.get("data") or {}
        if any(mime.startswith("image/") for mime in data):
            images += 1
        text = _join(output.get("text"))
        if not text:
            text = _join(data.get("text/plain"))
        if not text and output.get("output_type") == "error":
            text = f"{output.get('ename', '')}: {output.get('evalue', '')}"
        if text:
            chunks.append(text)
    joined = "\n".join(chunks).strip()
    if len(joined) > _MAX_SAVED_OUTPUT_CHARS:
        joined = joined[:_MAX_SAVED_OUTPUT_CHARS] + "\n…（输出较长，已截断；重新运行可看完整结果）"
    return joined, images


def parse_notebook(path: str | Path) -> ParsedNotebook:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    language = (
        (raw.get("metadata") or {}).get("kernelspec", {}).get("language")
        or (raw.get("metadata") or {}).get("language_info", {}).get("name")
        or "python"
    )

    parsed = ParsedNotebook(path=path)
    index = 0
    for cell in raw.get("cells") or []:
        source = _join(cell.get("source")).rstrip()
        kind = cell.get("cell_type")
        if kind not in ("code", "markdown") or not source.strip():
            continue
        index += 1
        saved_text, image_count = (
            _saved_output(cell.get("outputs") or []) if kind == "code" else ("", 0)
        )
        parsed.cells.append(
            NotebookCell(
                index=index,
                kind=kind,
                source=source,
                language=language if kind == "code" else "markdown",
                saved_output=saved_text,
                saved_image_count=image_count,
            )
        )
    return parsed


def to_teaching_markdown(parsed: ParsedNotebook) -> str:
    """把一份 notebook 转成适合放进检索库的教学 Markdown。

    第一层方案（课程进知识库）用它。体积约为原文的十分之一，因为图片没有跟进来。
    """
    parts: list[str] = []
    for cell in parsed.cells:
        if cell.kind == "markdown":
            parts.append(cell.source)
            continue
        parts.append(f"第 {cell.index} 格代码：\n\n```{cell.language}\n{cell.source}\n```")
        if cell.saved_output:
            parts.append(f"这一格的运行结果：\n\n```\n{cell.saved_output}\n```")
        if cell.saved_image_count:
            parts.append(f"（这一格还画出了 {cell.saved_image_count} 张图）")
    return "\n\n".join(parts) + "\n"


__all__ = ["NotebookCell", "ParsedNotebook", "parse_notebook", "to_teaching_markdown"]
