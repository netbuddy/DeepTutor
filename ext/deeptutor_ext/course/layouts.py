"""识别课程目录是哪种排布，并按各自的规矩读成「章 → 课 → 内容」。

目前认得两种：

* **notebook 型**：一层模块目录，每课一个子目录，里面是 README 讲义加一份 .ipynb
  练习（microsoft/ML-For-Beginners 是这一类）。
* **文档型**：一份 ``_toctree.yml`` 目录树驱动一堆 ``.mdx`` 正文，代码写在围栏里而不是
  notebook（huggingface 的课程是这一类）。

两种读出来的结果是同一种形状：一串章，每章一串课，每课一串内容片段。片段要么是讲解
文字，要么是一段代码。后面的导入器只认这个形状，再多一种课程排布也只要在这里加一个
识别函数，导入器不用动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re

from deeptutor_ext.course.notebook_io import NotebookParseError, parse_notebook

logger = logging.getLogger(__name__)

# 这些目录不该跟着导入：翻译副本会把同一课重复几十遍，其余是与学习内容无关的工程文件。
SKIP_DIRS = {
    "translations",
    "quiz-app",
    "node_modules",
    "pdf",
    ".git",
    ".github",
    "sketchnotes",
    "subtitles",
    "utils",
    "images",
    "assets",
}
_ORDERED_DIR = re.compile(r"^(\d+)-(.+)$")
_CHAPTER_DIR = re.compile(r"^chapter(\d+)$", re.IGNORECASE)


@dataclass
class Fragment:
    """一课里的一个片段：一段讲解，或者一段代码。"""

    kind: str  # "text" | "code"
    body: str
    title: str = ""
    language: str = "python"
    runnable: bool = False
    cwd: str = ""
    cell_index: int = 0
    saved_output: str = ""
    saved_image_count: int = 0
    source_label: str = ""


@dataclass
class Lesson:
    title: str
    key: str
    fragments: list[Fragment] = field(default_factory=list)


@dataclass
class Chapter:
    title: str
    key: str
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class CourseTree:
    title: str
    layout: str
    chapters: list[Chapter] = field(default_factory=list)
    # 读不了而被跳过的文件，导入完成后如实告诉用户，别让人以为内容凭空少了。
    skipped: list[str] = field(default_factory=list)

    @property
    def runnable_count(self) -> int:
        return sum(
            1
            for chapter in self.chapters
            for lesson in chapter.lessons
            for fragment in lesson.fragments
            if fragment.runnable
        )


# ── 公共小工具 ──────────────────────────────────────────────────────────────


def first_heading(path: Path, fallback: str) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                # HF 的标题带着 [[锚点]] 后缀，读起来碍事，去掉。
                return re.sub(r"\[\[.*?\]\]", "", stripped[2:]).strip()
    except OSError:
        pass
    return fallback


def pretty_name(dir_name: str) -> str:
    match = _ORDERED_DIR.match(dir_name)
    body = match.group(2) if match else dir_name
    return body.replace("-", " ").replace("_", " ").strip()


def order_of(dir_name: str) -> int:
    match = _ORDERED_DIR.match(dir_name) or _CHAPTER_DIR.match(dir_name)
    return int(match.group(1)) if match else 999


def split_markdown(text: str, max_chars: int = 2500) -> list[tuple[str, str]]:
    """按二级标题把长文切成若干段，返回 (小标题, 正文)。

    切开是为了让页面可以逐段阅读、逐段提问；不切的话一页就是一大坨文字。
    段落过长时按空行再切一刀。
    """
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if buffer:
                sections.append((heading, buffer))
            heading = re.sub(r"\[\[.*?\]\]", "", line[3:]).strip()
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
                result.append((f"{title}（续 {part}）" if title and part > 1 else title, "\n\n".join(chunk)))
                chunk, size, part = [], 0, part + 1
            chunk.append(paragraph)
            size += len(paragraph)
        if chunk:
            result.append((f"{title}（续 {part}）" if title and part > 1 else title, "\n\n".join(chunk)))
    return result


# ── 排布识别 ────────────────────────────────────────────────────────────────


def detect_layout(root: Path) -> str:
    """判断这个课程目录是哪种排布。"""
    if list(root.glob("chapters/*/_toctree.yml")) or (root / "_toctree.yml").is_file():
        return "toctree"
    if list(root.rglob("*.ipynb")):
        return "notebook"
    if list(root.rglob("*.md")) or list(root.rglob("*.mdx")):
        return "docs"
    return "unknown"


# ── notebook 型 ─────────────────────────────────────────────────────────────


def _module_dirs(root: Path) -> list[Path]:
    return sorted(
        (
            p
            for p in root.iterdir()
            if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith(".")
        ),
        key=lambda p: (order_of(p.name), p.name),
    )


def _lesson_dirs(module: Path) -> list[Path]:
    return sorted(
        (
            p
            for p in module.iterdir()
            if p.is_dir()
            and p.name not in SKIP_DIRS
            and not p.name.startswith(".")
            and p.name not in {"data", "solution", "working"}
        ),
        key=lambda p: (order_of(p.name), p.name),
    )


def _has_code(path: Path, skipped: list[str]) -> bool:
    """这份 notebook 能读且有代码格吗？读不了就记一笔并当作没有。"""
    try:
        return bool(parse_notebook(path).code_cells)
    except NotebookParseError as exc:
        skipped.append(str(exc))
        logger.warning("跳过读不了的 notebook：%s", exc)
        return False


def _pick_notebook(lesson: Path, skipped: list[str]) -> Path | None:
    """挑这一课要展示的 notebook。

    优先答案本：课程给学生的练习本多数是空壳（只有一个空格子），带讲解和完整代码的
    是答案本，它才是可以逐格运行的教学材料。读不了的文件跳过——外部课程里
    Git LFS 指针、空文件、坏编码都可能出现，不该因为一份坏文件让整门课导不进来。
    """
    for candidate in (lesson / "solution" / "notebook.ipynb", lesson / "notebook.ipynb"):
        if candidate.is_file() and _has_code(candidate, skipped):
            return candidate
    for candidate in sorted(lesson.rglob("*.ipynb")):
        if "R" in candidate.parts:  # R 语言版本跳过，内核只有 Python
            continue
        if _has_code(candidate, skipped):
            return candidate
    return None


def _fragments_from_markdown(text: str, label: str) -> list[Fragment]:
    return [
        Fragment(kind="text", body=body, title=title, source_label=label)
        for title, body in split_markdown(text)
    ]


def read_notebook_layout(root: Path, title: str) -> CourseTree:
    tree = CourseTree(title=title, layout="notebook")
    for module in _module_dirs(root):
        lessons = _lesson_dirs(module)
        if not lessons:
            continue
        chapter = Chapter(
            title=first_heading(module / "README.md", pretty_name(module.name)),
            key=module.name,
        )
        for lesson_dir in lessons:
            readme = lesson_dir / "README.md"
            notebook_path = _pick_notebook(lesson_dir, tree.skipped)
            if not readme.is_file() and notebook_path is None:
                continue
            lesson = Lesson(
                title=first_heading(readme, pretty_name(lesson_dir.name)),
                key=f"{module.name}_{lesson_dir.name}",
            )
            if readme.is_file():
                lesson.fragments += _fragments_from_markdown(
                    readme.read_text(encoding="utf-8"), str(readme.relative_to(root))
                )
            if notebook_path is not None:
                label = str(notebook_path.relative_to(root))
                try:
                    parsed = parse_notebook(notebook_path)
                except NotebookParseError as exc:
                    tree.skipped.append(str(exc))
                    parsed = None
            if notebook_path is not None and parsed is not None:
                for cell in parsed.cells:
                    if cell.kind == "markdown":
                        lesson.fragments += _fragments_from_markdown(cell.source, label)
                        continue
                    lesson.fragments.append(
                        Fragment(
                            kind="code",
                            body=cell.source,
                            title=f"第 {cell.index} 格",
                            language=cell.language,
                            runnable=True,
                            cwd=parsed.cwd,
                            cell_index=cell.index,
                            saved_output=cell.saved_output,
                            saved_image_count=cell.saved_image_count,
                            source_label=label,
                        )
                    )
            assignment = lesson_dir / "assignment.md"
            if assignment.is_file():
                lesson.fragments += _fragments_from_markdown(
                    assignment.read_text(encoding="utf-8"), str(assignment.relative_to(root))
                )
            if lesson.fragments:
                chapter.lessons.append(lesson)
        if chapter.lessons:
            tree.chapters.append(chapter)
    return tree


# ── 文档型（_toctree.yml 驱动的 mdx） ───────────────────────────────────────

# MDX 里混着 React 组件，它们在纯 Markdown 里渲染不出来，只会留下一串尖括号噪声。
_MDX_SELF_CLOSING = re.compile(r"<([A-Z][\w.]*)\b[^>]*/>", re.S)
_MDX_IMPORT = re.compile(r"^import\s+.*$", re.M)
# 这些成对标签的内容是有用的正文（提示、警告），只脱掉外壳。
_MDX_KEEP_INNER = re.compile(
    r"<(Tip|Note|Warning|Question|Youtube|CourseFloatingBanner)\b[^>]*>(.*?)</\1>", re.S
)
_MDX_OTHER_PAIR = re.compile(r"<([A-Z][\w.]*)\b[^>]*>(.*?)</\1>", re.S)
_CODE_FENCE = re.compile(r"^```([\w+-]*)\n(.*?)^```", re.M | re.S)
_RUNNABLE_LANGS = {"py", "python", "python3"}


def clean_mdx(text: str) -> str:
    """把 MDX 里的组件标记去掉，只留下 Markdown 能表达的部分。"""
    text = _MDX_IMPORT.sub("", text)
    text = _MDX_KEEP_INNER.sub(lambda m: m.group(2), text)
    text = _MDX_OTHER_PAIR.sub(lambda m: m.group(2), text)
    text = _MDX_SELF_CLOSING.sub("", text)
    text = re.sub(r"\[\[.*?\]\]", "", text)  # 标题后缀的锚点
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_prose_and_code(text: str, label: str, cwd: str) -> list[Fragment]:
    """把一篇正文按代码围栏切开：围栏外是讲解，围栏内是代码。"""
    fragments: list[Fragment] = []
    cursor = 0
    index = 0
    for match in _CODE_FENCE.finditer(text):
        prose = text[cursor : match.start()].strip()
        if prose:
            fragments += _fragments_from_markdown(prose, label)
        language = (match.group(1) or "").lower()
        code = match.group(2).rstrip()
        if code.strip():
            index += 1
            runnable = language in _RUNNABLE_LANGS
            fragments.append(
                Fragment(
                    kind="code" if runnable else "text",
                    body=code if runnable else f"```{language}\n{code}\n```",
                    title=f"第 {index} 段代码" if runnable else "",
                    language=language or "text",
                    runnable=runnable,
                    cwd=cwd,
                    cell_index=index,
                    source_label=label,
                )
            )
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        fragments += _fragments_from_markdown(tail, label)
    return fragments


def _parse_toctree(path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    """读 ``_toctree.yml``，返回 [(章标题, [(课标题, 相对路径), …]), …]。

    这份文件的结构很规整（只有 title / sections / local 三种键），所以手写解析，
    省掉一个 YAML 依赖。格式变了会解析成空，调用方会退回按目录扫描。
    """
    chapters: list[tuple[str, list[tuple[str, str]]]] = []
    current_title = ""
    current_sections: list[tuple[str, str]] = []
    pending_local = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0 and stripped.startswith("- title:"):
            if current_title and current_sections:
                chapters.append((current_title, current_sections))
            current_title = stripped.split(":", 1)[1].strip().strip("\"'")
            current_sections = []
            pending_local = ""
        elif stripped.startswith("- local:"):
            pending_local = stripped.split(":", 1)[1].strip().strip("\"'")
        elif stripped.startswith("title:") and pending_local:
            section_title = stripped.split(":", 1)[1].strip().strip("\"'")
            current_sections.append((section_title, pending_local))
            pending_local = ""
    if current_title and current_sections:
        chapters.append((current_title, current_sections))
    return chapters


def _toctree_dir(root: Path, language: str) -> Path | None:
    """找出用哪一份语言的目录树。找不到指定语言就退回英文，再不行就取第一个。"""
    candidates = sorted(root.glob("chapters/*/_toctree.yml"))
    if (root / "_toctree.yml").is_file():
        candidates.append(root / "_toctree.yml")
    if not candidates:
        return None
    wanted = {language.lower(), language.lower().replace("-", "_")}
    if language.lower().startswith("zh"):
        wanted |= {"zh-cn", "zh_cn", "zh"}
    for candidate in candidates:
        if candidate.parent.name.lower() in wanted:
            return candidate.parent
    for candidate in candidates:
        if candidate.parent.name.lower() == "en":
            return candidate.parent
    return candidates[0].parent


def read_toctree_layout(root: Path, title: str, language: str = "en") -> CourseTree:
    base = _toctree_dir(root, language)
    tree = CourseTree(title=title, layout="toctree")
    if base is None:
        return tree

    entries = _parse_toctree(base / "_toctree.yml")
    for chapter_title, sections in entries:
        chapter = Chapter(title=chapter_title, key=chapter_title)
        for lesson_title, local in sections:
            page_file = None
            for suffix in (".mdx", ".md"):
                candidate = base / f"{local}{suffix}"
                if candidate.is_file():
                    page_file = candidate
                    break
            if page_file is None:
                continue
            label = str(page_file.relative_to(root))
            cleaned = clean_mdx(page_file.read_text(encoding="utf-8"))
            fragments = _split_prose_and_code(cleaned, label, str(page_file.parent))
            if not fragments:
                continue
            chapter.lessons.append(
                Lesson(
                    title=lesson_title or first_heading(page_file, local),
                    key=local.replace("/", "_"),
                    fragments=fragments,
                )
            )
        if chapter.lessons:
            tree.chapters.append(chapter)
    return tree


def read_course(root: Path, title: str, *, language: str = "en") -> CourseTree:
    """按识别出的排布把课程读成统一形状。"""
    layout = detect_layout(root)
    if layout == "toctree":
        tree = read_toctree_layout(root, title, language=language)
        if tree.chapters:
            return tree
        logger.warning("目录树解析不出内容，退回按目录扫描：%s", root)
    return read_notebook_layout(root, title)


__all__ = [
    "Chapter",
    "CourseTree",
    "Fragment",
    "Lesson",
    "clean_mdx",
    "detect_layout",
    "read_course",
    "split_markdown",
]
