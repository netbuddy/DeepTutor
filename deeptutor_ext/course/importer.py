"""把一个课程仓库变成 DeepTutor 里的一本书。

课程仓库的目录结构是规整的，可以机械地映射到 Book 的三层结构上：

    课程根目录          →  一本书
    2-Regression/       →  一章
    2-Regression/3-Linear/  →  一页
    页里的内容块        →  讲义正文、可运行的代码格、作业说明

代码格用的是 Book 现成的 ``code`` 块类型，只是在它的 payload 里多挂一段 ``notebook``
信息（源文件、执行时的工作目录、这是第几格）。这样后端一行都不用改——Book 的块模型
本来就允许自定义字段——前端只要认得这段信息，就知道该给这一格画上运行按钮。

生成的书按课程标识取固定的 id，重复导入是覆盖而不是新增一本。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from pathlib import Path
import time

from deeptutor_ext.course.notebook_io import ParsedNotebook, parse_notebook

logger = logging.getLogger(__name__)

# 课程仓库里那些不该跟着导入的目录：翻译副本会把同一课重复几十遍，测验应用和
# 打包产物则与学习内容无关。
_SKIP_DIRS = {"translations", "quiz-app", "node_modules", "pdf", ".git", ".github", "sketchnotes"}
# 模块目录形如 "2-Regression"，课时目录形如 "3-Linear"，都以序号开头。
_ORDERED_DIR = re.compile(r"^(\d+)-(.+)$")


@dataclass
class ImportStats:
    chapters: int = 0
    pages: int = 0
    text_blocks: int = 0
    code_blocks: int = 0
    runnable_cells: int = 0

    def describe(self) -> str:
        return (
            f"{self.chapters} 章、{self.pages} 页，"
            f"其中讲解块 {self.text_blocks} 个、代码块 {self.code_blocks} 个"
            f"（可运行的单元格 {self.runnable_cells} 个）"
        )


def _title_from_readme(readme: Path, fallback: str) -> str:
    """取 Markdown 里的第一个一级标题作为标题。"""
    try:
        for line in readme.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    except OSError:
        pass
    return fallback


def _pretty_name(dir_name: str) -> str:
    match = _ORDERED_DIR.match(dir_name)
    body = match.group(2) if match else dir_name
    return body.replace("-", " ").replace("_", " ").strip()


def _order_of(dir_name: str) -> int:
    match = _ORDERED_DIR.match(dir_name)
    return int(match.group(1)) if match else 999


def _split_markdown(text: str, max_chars: int = 2500) -> list[tuple[str, str]]:
    """按二级标题把讲义切成若干段，返回 (小标题, 正文) 的列表。

    切开是为了让页面可以逐段阅读、逐段提问；不切的话一页就是一大坨文字，
    「就这一段提问」也就无从谈起。段落过长时按段落再切一刀。
    """
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    buffer: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if buffer:
                sections.append((heading, buffer))
            heading = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        sections.append((heading, buffer))

    result: list[tuple[str, str]] = []
    for title, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        if len(body) <= max_chars:
            result.append((title, body))
            continue
        chunk: list[str] = []
        size = 0
        part = 1
        for paragraph in body.split("\n\n"):
            if size + len(paragraph) > max_chars and chunk:
                suffix = f"（续 {part}）" if part > 1 else ""
                result.append((title + suffix if title else "", "\n\n".join(chunk)))
                chunk, size, part = [], 0, part + 1
            chunk.append(paragraph)
            size += len(paragraph)
        if chunk:
            suffix = f"（续 {part}）" if part > 1 else ""
            result.append((title + suffix if title else "", "\n\n".join(chunk)))
    return result


class CourseImporter:
    """把课程目录读成一本 Book 并存下来。"""

    def __init__(self, course_root: str | Path, *, language: str = "zh") -> None:
        self.root = Path(course_root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"课程目录不存在：{self.root}")
        self.language = language
        self.stats = ImportStats()

    # ── 结构发现 ────────────────────────────────────────────────────────

    def _module_dirs(self) -> list[Path]:
        return sorted(
            (
                p
                for p in self.root.iterdir()
                if p.is_dir() and p.name not in _SKIP_DIRS and not p.name.startswith(".")
            ),
            key=lambda p: (_order_of(p.name), p.name),
        )

    def _lesson_dirs(self, module: Path) -> list[Path]:
        return sorted(
            (
                p
                for p in module.iterdir()
                if p.is_dir()
                and p.name not in _SKIP_DIRS
                and not p.name.startswith(".")
                and p.name not in {"data", "images", "solution", "working"}
            ),
            key=lambda p: (_order_of(p.name), p.name),
        )

    @staticmethod
    def _lesson_notebook(lesson: Path) -> Path | None:
        """挑这一课要展示的 notebook。

        优先用 solution 目录下的那份：课程里给学生的练习本多数是空壳（只有一个空格子），
        真正带讲解和完整代码的是答案本，它才是可以逐格运行的教学材料。
        """
        candidates = [
            lesson / "solution" / "notebook.ipynb",
            lesson / "notebook.ipynb",
        ]
        for candidate in candidates:
            if candidate.is_file():
                parsed = parse_notebook(candidate)
                if parsed.code_cells:
                    return candidate
        for candidate in sorted(lesson.rglob("*.ipynb")):
            if "R" in candidate.parts:  # R 语言版本跳过，内核只有 Python
                continue
            if parse_notebook(candidate).code_cells:
                return candidate
        return None

    # ── 块构造 ──────────────────────────────────────────────────────────

    def _text_blocks(self, markdown: str, source_label: str) -> list:
        from deeptutor.book.models import Block, BlockStatus, BlockType

        blocks = []
        for title, body in _split_markdown(markdown):
            blocks.append(
                Block(
                    type=BlockType.TEXT,
                    status=BlockStatus.READY,
                    title=title,
                    payload={"markdown": body, "text": body},
                    metadata={"origin": "course_import", "source": source_label},
                )
            )
            self.stats.text_blocks += 1
        return blocks

    def _notebook_blocks(self, parsed: ParsedNotebook, source_label: str) -> list:
        from deeptutor.book.models import Block, BlockStatus, BlockType

        blocks = []
        for cell in parsed.cells:
            if cell.kind == "markdown":
                blocks.extend(self._text_blocks(cell.source, source_label))
                continue
            blocks.append(
                Block(
                    type=BlockType.CODE,
                    status=BlockStatus.READY,
                    title=f"第 {cell.index} 格",
                    payload={
                        "language": cell.language,
                        "code": cell.source,
                        "explanation": "",
                        # 这段是我们加的。前端认得它就给这一格画运行按钮，
                        # 认不得也不影响——退化成一段普通的代码展示。
                        "notebook": {
                            "source": source_label,
                            "cwd": parsed.cwd,
                            "cell_index": cell.index,
                            "runnable": True,
                            "saved_output": cell.saved_output,
                            "saved_image_count": cell.saved_image_count,
                        },
                    },
                    metadata={"origin": "course_import", "source": source_label},
                )
            )
            self.stats.code_blocks += 1
            self.stats.runnable_cells += 1
        return blocks

    # ── 主流程 ──────────────────────────────────────────────────────────

    def build(self, *, book_id: str = "") -> tuple[object, object, list]:
        from deeptutor.book.models import (
            Book,
            BookStatus,
            Chapter,
            ContentType,
            Page,
            PageStatus,
            Spine,
        )

        slug = re.sub(r"[^a-z0-9]+", "-", self.root.name.lower()).strip("-") or "course"
        resolved_id = book_id or f"bk_course_{slug}"[:48]

        readme = self.root / "README.md"
        book = Book(
            id=resolved_id,
            title=_title_from_readme(readme, _pretty_name(self.root.name)),
            description=f"从课程目录 {self.root} 导入。",
            status=BookStatus.READY,
            language=self.language,
            metadata={
                "origin": "course_import",
                "course_root": str(self.root),
                "imported_at": time.time(),
            },
        )

        chapters: list[Chapter] = []
        pages: list[Page] = []

        for order, module in enumerate(self._module_dirs(), start=1):
            lesson_dirs = self._lesson_dirs(module)
            if not lesson_dirs:
                continue
            module_readme = module / "README.md"
            chapter = Chapter(
                id=f"ch_{module.name.lower().replace('-', '_')}"[:48],
                title=_title_from_readme(module_readme, _pretty_name(module.name)),
                content_type=ContentType.PRACTICE,
                order=order,
                summary=f"课程模块 {module.name}",
            )

            for page_order, lesson in enumerate(lesson_dirs, start=1):
                lesson_readme = lesson / "README.md"
                notebook_path = self._lesson_notebook(lesson)
                if not lesson_readme.is_file() and notebook_path is None:
                    continue

                page = Page(
                    id=f"pg_{module.name.lower()}_{lesson.name.lower()}".replace("-", "_")[:48],
                    book_id=book.id,
                    chapter_id=chapter.id,
                    title=_title_from_readme(lesson_readme, _pretty_name(lesson.name)),
                    content_type=ContentType.PRACTICE,
                    status=PageStatus.READY,
                    order=page_order,
                )

                if lesson_readme.is_file():
                    label = str(lesson_readme.relative_to(self.root))
                    page.blocks.extend(
                        self._text_blocks(lesson_readme.read_text(encoding="utf-8"), label)
                    )

                if notebook_path is not None:
                    parsed = parse_notebook(notebook_path)
                    label = str(notebook_path.relative_to(self.root))
                    page.blocks.extend(self._notebook_blocks(parsed, label))

                assignment = lesson / "assignment.md"
                if assignment.is_file():
                    label = str(assignment.relative_to(self.root))
                    page.blocks.extend(
                        self._text_blocks(assignment.read_text(encoding="utf-8"), label)
                    )

                if not page.blocks:
                    continue
                chapter.page_ids.append(page.id)
                pages.append(page)
                self.stats.pages += 1

            if not chapter.page_ids:
                continue
            chapters.append(chapter)
            self.stats.chapters += 1

        book.chapter_count = len(chapters)
        book.page_count = len(pages)
        spine = Spine(book_id=book.id, chapters=chapters)
        return book, spine, pages

    def save(self, *, book_id: str = "") -> str:
        from deeptutor.book.storage import BookStorage

        book, spine, pages = self.build(book_id=book_id)
        storage = BookStorage()
        storage.save_book(book)
        storage.save_spine(spine)
        for page in pages:
            storage.save_page(page)
        logger.info("课程已导入为书 %s：%s", book.id, self.stats.describe())
        return book.id


__all__ = ["CourseImporter", "ImportStats"]
