"""课程的生命周期：取来源、导成书、建检索索引、登记、删除。

一门课在 DeepTutor 里最终摊成三样东西：

* **课程目录**（``data/user/courses/<标识>/``）——原始文件，执行容器只读挂载这一份，
  页面上跑代码时的工作目录就在里面；
* **一本书**——章节目录加可运行的页面，学生在这里读和练；
* **一个知识库**（可选）——全课正文的检索索引，绑在书上，于是书页里的对话面板
  会自动打开检索，学生问「这门课哪里讲过 X」时助教能翻遍全课回答。

课程清单存在一个 JSON 文件里，记着每门课的来源、标识、对应的书和知识库。它是这三样
东西之间唯一的连接点，删课时靠它把三边一起清干净。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path
import re
import time

from deeptutor_ext.course.importer import CourseImporter, book_id_for
from deeptutor_ext.course.layouts import read_course
from deeptutor_ext.course.sources import SourceError, courses_root, fetch, remove, slugify

logger = logging.getLogger(__name__)

REGISTRY_FILENAME = "ext_courses.json"
# 知识库名称有格式要求（字母数字加连字符），课程标识本来就是这个形状，加个前缀避免撞名。
KB_PREFIX = "course-"


@dataclass
class CourseRecord:
    slug: str
    title: str
    origin: str = ""
    kind: str = "local"  # git | local
    layout: str = ""  # notebook | toctree
    language: str = "zh"
    book_id: str = ""
    kb_name: str = ""
    size_mb: float = 0.0
    stats: dict = field(default_factory=dict)
    imported_at: float = 0.0
    indexed_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _registry_path() -> Path:
    from deeptutor.services.path_service import get_path_service

    return get_path_service().get_settings_dir() / REGISTRY_FILENAME


def _load_registry() -> dict[str, CourseRecord]:
    path = _registry_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("课程清单读不出来，按空清单处理：%s", path)
        return {}
    records: dict[str, CourseRecord] = {}
    for slug, item in (raw.get("courses") or {}).items():
        try:
            records[slug] = CourseRecord(**item)
        except TypeError:
            # 清单是我们自己写的，字段对不上说明是旧版本留下的，跳过即可。
            logger.warning("课程清单里有一条读不了的记录，已跳过：%s", slug)
    return records


def _save_registry(records: dict[str, CourseRecord]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "courses": {slug: r.to_dict() for slug, r in records.items()}}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _index_dir(slug: str) -> Path:
    """建检索索引时用的中间目录：全课正文摊成一课一个 Markdown 文件。

    不放进课程目录，是因为那里是原始资料，下次重新导入会被整体替换掉。
    """
    from deeptutor.services.path_service import get_path_service

    path = get_path_service().get_workspace_dir() / "course_index" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def kb_name_for(slug: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9-]+", "-", f"{KB_PREFIX}{slug}").strip("-")
    return name[:48]


class CourseService:
    """课程模块的门面。API 与命令行都走这里，行为保持一致。"""

    def list_courses(self) -> list[CourseRecord]:
        records = _load_registry()
        # 目录被手工删掉的课程不该继续出现在列表里，顺手对一次账。
        alive = {slug: r for slug, r in records.items() if (courses_root() / slug).is_dir()}
        if len(alive) != len(records):
            _save_registry(alive)
        return sorted(alive.values(), key=lambda r: r.imported_at, reverse=True)

    def get(self, slug: str) -> CourseRecord | None:
        return _load_registry().get(slugify(slug))

    # ── 创建 ────────────────────────────────────────────────────────────

    def create(
        self,
        origin: str,
        *,
        title: str = "",
        slug: str = "",
        language: str = "zh",
        branch: str = "",
        replace: bool = False,
    ) -> CourseRecord:
        """取来源、导成书、登记。不建检索索引——那一步慢，单独触发。"""
        fetched = fetch(origin, slug=slugify(slug) if slug else "", branch=branch, replace=replace)
        importer = CourseImporter(fetched.path, title=title, language=language)
        book_id = importer.save(slug=fetched.slug)
        tree = importer.tree

        records = _load_registry()
        previous = records.get(fetched.slug)
        record = CourseRecord(
            slug=fetched.slug,
            title=importer.title if not tree else (tree.title or importer.title),
            origin=fetched.origin,
            kind=fetched.kind,
            layout=tree.layout if tree else "",
            language=language,
            book_id=book_id,
            kb_name=previous.kb_name if previous else "",
            size_mb=fetched.size_mb,
            stats=importer.stats.to_dict(),
            imported_at=time.time(),
            indexed_at=previous.indexed_at if previous else 0.0,
        )
        records[record.slug] = record
        _save_registry(records)
        return record

    # ── 检索索引 ────────────────────────────────────────────────────────

    def export_markdown(self, slug: str) -> tuple[Path, int]:
        """把全课正文摊成一课一个 Markdown 文件，返回（目录，文件数）。

        代码也写进去（带围栏），这样学生问「哪一课出现过 tokenizer」时能检索到代码。
        图片不跟过来——课程里的插图对文字检索没有帮助，只会撑大索引。
        """
        record = self.get(slug)
        if record is None:
            raise SourceError(f"没有这门课：{slug}")
        root = courses_root() / record.slug
        tree = read_course(root, record.title, language=record.language)

        target = _index_dir(record.slug)
        for stale in target.glob("*.md"):
            stale.unlink()

        written = 0
        for chapter_no, chapter in enumerate(tree.chapters, start=1):
            for lesson_no, lesson in enumerate(chapter.lessons, start=1):
                parts = [f"# {chapter.title} / {lesson.title}", ""]
                for fragment in lesson.fragments:
                    if fragment.kind == "code":
                        parts.append(f"```{fragment.language}\n{fragment.body}\n```")
                    else:
                        if fragment.title:
                            parts.append(f"## {fragment.title}")
                        parts.append(fragment.body)
                    parts.append("")
                name = f"{chapter_no:02d}-{lesson_no:02d}-{_safe_filename(lesson.title)}.md"
                (target / name).write_text("\n".join(parts), encoding="utf-8")
                written += 1
        return target, written

    async def build_index(self, slug: str) -> str:
        """给这门课建知识库并绑到它的书上。已经有索引就重建。"""
        record = self.get(slug)
        if record is None:
            raise SourceError(f"没有这门课：{slug}")

        target, count = self.export_markdown(record.slug)
        if not count:
            raise SourceError("这门课没有解析出正文，无法建索引。")

        from deeptutor.knowledge.add_documents import add_documents
        from deeptutor.knowledge.initializer import initialize_knowledge_base
        from deeptutor.knowledge.manager import KnowledgeBaseManager

        manager = KnowledgeBaseManager()
        kb_name = record.kb_name or kb_name_for(record.slug)
        files = sorted(str(p) for p in target.glob("*.md"))

        # 已经登记过的知识库走「补文档」，没有的走「新建」。但登记表里有名字不等于
        # 索引真的建成过——上一次建到一半失败就会留下这种半成品，补文档时会报
        # 「knowledge base not initialized」。碰到这种情况删掉重建，而不是把错误抛给用户。
        if kb_name in manager.list_knowledge_bases():
            try:
                await add_documents(
                    kb_name=kb_name,
                    source_files=files,
                    base_dir=str(manager.base_dir),
                    allow_duplicates=False,
                )
            except Exception as exc:
                if "not initialized" not in str(exc).lower():
                    raise
                logger.warning("知识库 %s 是上次没建完的半成品，删掉重建", kb_name)
                manager.delete_knowledge_base(kb_name, confirm=True)
                await initialize_knowledge_base(
                    kb_name=kb_name,
                    source_files=files,
                    base_dir=str(manager.base_dir),
                )
        else:
            await initialize_knowledge_base(
                kb_name=kb_name,
                source_files=files,
                base_dir=str(manager.base_dir),
            )

        self._bind_kb_to_book(record.book_id, kb_name)

        records = _load_registry()
        stored = records.get(record.slug)
        if stored is not None:
            stored.kb_name = kb_name
            stored.indexed_at = time.time()
            _save_registry(records)
        logger.info("课程 %s 的检索索引已建好：%s（%d 篇）", record.slug, kb_name, count)
        return kb_name

    @staticmethod
    def _bind_kb_to_book(book_id: str, kb_name: str) -> None:
        """把知识库挂到书上。书页对话面板看到有知识库就会打开检索工具。"""
        from deeptutor.book.storage import BookStorage

        storage = BookStorage()
        book = storage.load_book(book_id)
        if book is None:
            logger.warning("课程对应的书 %s 不在了，跳过绑定知识库", book_id)
            return
        if kb_name not in book.knowledge_bases:
            book.knowledge_bases = [*book.knowledge_bases, kb_name]
            storage.save_book(book)

    # ── 删除 ────────────────────────────────────────────────────────────

    def delete(self, slug: str, *, drop_book: bool = True, drop_kb: bool = True) -> dict:
        record = self.get(slug)
        if record is None:
            raise SourceError(f"没有这门课：{slug}")

        outcome = {"course_dir": remove(record.slug), "book": False, "kb": False}

        if drop_book and record.book_id:
            from deeptutor.book.storage import BookStorage

            storage = BookStorage()
            root = storage.book_root(record.book_id)
            if root.is_dir():
                import shutil

                shutil.rmtree(root)
                outcome["book"] = True

        if drop_kb and record.kb_name:
            from deeptutor.knowledge.manager import KnowledgeBaseManager

            manager = KnowledgeBaseManager()
            if record.kb_name in manager.list_knowledge_bases():
                manager.delete_knowledge_base(record.kb_name, confirm=True)
                outcome["kb"] = True

        index_dir = _index_dir(record.slug)
        if index_dir.is_dir():
            import shutil

            shutil.rmtree(index_dir, ignore_errors=True)

        records = _load_registry()
        records.pop(record.slug, None)
        _save_registry(records)
        return outcome


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^\w一-鿿-]+", "-", value.strip()).strip("-")
    return (cleaned or "lesson")[:60]


_service: CourseService | None = None


def get_course_service() -> CourseService:
    global _service
    if _service is None:
        _service = CourseService()
    return _service


__all__ = ["CourseRecord", "CourseService", "book_id_for", "get_course_service", "kb_name_for"]
