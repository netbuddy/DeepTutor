"""把读好的课程结构写成 DeepTutor 里的一本书。

课程的三层结构直接对上 Book 的三层：章对章，课对页，课里的片段对页里的内容块。
代码片段用 Book 现成的 ``code`` 块类型，只是在它的 payload 里多挂一段 ``notebook``
信息（源文件、执行时的工作目录、这是第几段）。这样后端一行都不用改——Book 的块模型
本来就允许自定义字段——前端认得那段信息就知道该给这一段画上运行按钮。

生成的书按课程标识取固定的 id，重复导入是覆盖而不是新增一本。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import time

from deeptutor_ext.course.layouts import CourseTree, read_course

logger = logging.getLogger(__name__)


@dataclass
class ImportStats:
    chapters: int = 0
    pages: int = 0
    text_blocks: int = 0
    code_blocks: int = 0
    runnable_cells: int = 0
    skipped_files: int = 0

    def describe(self) -> str:
        text = (
            f"{self.chapters} 章、{self.pages} 页，"
            f"其中讲解块 {self.text_blocks} 个、代码块 {self.code_blocks} 个"
            f"（可运行的 {self.runnable_cells} 个）"
        )
        if self.skipped_files:
            text += f"；另有 {self.skipped_files} 个文件读不了，已跳过"
        return text

    def to_dict(self) -> dict[str, int]:
        return {
            "chapters": self.chapters,
            "pages": self.pages,
            "text_blocks": self.text_blocks,
            "code_blocks": self.code_blocks,
            "runnable_cells": self.runnable_cells,
            "skipped_files": self.skipped_files,
        }


def book_id_for(slug: str) -> str:
    return f"bk_course_{slug}"[:48]


class CourseImporter:
    """把课程目录读成一本 Book 并存下来。"""

    def __init__(self, course_root: str | Path, *, title: str = "", language: str = "zh") -> None:
        self.root = Path(course_root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"课程目录不存在：{self.root}")
        self.language = language
        self.title = title or self.root.name
        self.stats = ImportStats()
        self.tree: CourseTree | None = None

    # ── 块构造 ──────────────────────────────────────────────────────────

    def _text_block(self, fragment):
        from deeptutor.book.models import Block, BlockStatus, BlockType

        self.stats.text_blocks += 1
        return Block(
            type=BlockType.TEXT,
            status=BlockStatus.READY,
            title=fragment.title,
            payload={"markdown": fragment.body, "text": fragment.body},
            metadata={"origin": "course_import", "source": fragment.source_label},
        )

    def _code_block(self, fragment):
        from deeptutor.book.models import Block, BlockStatus, BlockType

        self.stats.code_blocks += 1
        if fragment.runnable:
            self.stats.runnable_cells += 1
        return Block(
            type=BlockType.CODE,
            status=BlockStatus.READY,
            title=fragment.title,
            payload={
                "language": fragment.language,
                "code": fragment.body,
                "explanation": "",
                # 这段是我们加的。前端认得它就给这一段画运行按钮，
                # 认不得也不影响——退化成一段普通的代码展示。
                "notebook": {
                    "source": fragment.source_label,
                    "cwd": fragment.cwd,
                    "cell_index": fragment.cell_index,
                    "runnable": fragment.runnable,
                    "saved_output": fragment.saved_output,
                    "saved_image_count": fragment.saved_image_count,
                },
            },
            metadata={"origin": "course_import", "source": fragment.source_label},
        )

    # ── 主流程 ──────────────────────────────────────────────────────────

    def build(self, *, slug: str) -> tuple[object, object, list]:
        from deeptutor.book.models import (
            Book,
            BookStatus,
            Chapter,
            ContentType,
            Page,
            PageStatus,
            Spine,
        )

        self.tree = read_course(self.root, self.title, language=self.language)
        book = Book(
            id=book_id_for(slug),
            title=self.tree.title or self.title,
            description=f"从课程目录 {self.root.name} 导入。",
            status=BookStatus.READY,
            language=self.language,
            metadata={
                "origin": "course_import",
                "course_slug": slug,
                "course_root": str(self.root),
                "layout": self.tree.layout,
                "imported_at": time.time(),
            },
        )

        chapters: list[Chapter] = []
        pages: list[Page] = []

        for order, source_chapter in enumerate(self.tree.chapters, start=1):
            chapter = Chapter(
                id=f"ch_{slug}_{order}"[:48],
                title=source_chapter.title,
                content_type=ContentType.PRACTICE,
                order=order,
                summary="",
            )
            for page_order, lesson in enumerate(source_chapter.lessons, start=1):
                page = Page(
                    id=f"pg_{slug}_{order}_{page_order}"[:48],
                    book_id=book.id,
                    chapter_id=chapter.id,
                    title=lesson.title,
                    content_type=ContentType.PRACTICE,
                    status=PageStatus.READY,
                    order=page_order,
                )
                for fragment in lesson.fragments:
                    page.blocks.append(
                        self._code_block(fragment)
                        if fragment.kind == "code"
                        else self._text_block(fragment)
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
        self.stats.skipped_files = len(self.tree.skipped)
        if self.tree.skipped:
            book.metadata["skipped_files"] = self.tree.skipped[:50]
        return book, Spine(book_id=book.id, chapters=chapters), pages

    def save(self, *, slug: str, knowledge_bases: list[str] | None = None) -> str:
        from deeptutor.book.storage import BookStorage

        book, spine, pages = self.build(slug=slug)
        if knowledge_bases:
            # 书页里的对话面板看到书上绑了知识库就会打开检索工具，
            # 于是学生问「这门课后面讲没讲过 X」时能从全课正文里找答案。
            book.knowledge_bases = list(knowledge_bases)

        storage = BookStorage()
        # 重新导入同一门课时，先清掉旧页：课程结构可能变了，留着孤儿页会让目录对不上。
        _drop_pages(storage, book.id, keep={page.id for page in pages})
        storage.save_book(book)
        storage.save_spine(spine)
        for page in pages:
            storage.save_page(page)
        logger.info("课程已导入为书 %s：%s", book.id, self.stats.describe())
        return book.id


def _drop_pages(storage, book_id: str, *, keep: set[str]) -> None:
    """删掉这次不再出现的旧页。

    重新导入同一门课时课程结构可能变了，留着上一次的孤儿页会让目录里点开是空白。
    """
    pages_dir = storage.book_root(book_id) / "pages"
    if not pages_dir.is_dir():
        return
    for page_file in pages_dir.glob("*.json"):
        if page_file.stem not in keep:
            page_file.unlink(missing_ok=True)


__all__ = ["CourseImporter", "ImportStats", "book_id_for"]
