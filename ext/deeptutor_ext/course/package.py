"""课程包：把一门课打成一个文件，拿到别的机器上导进去还是同一门课。

包里只放**课程源文件**加一份元数据，不放生成出来的课本和检索索引。原因是那两样
都带着本机的绝对路径（代码执行时的工作目录就写在课本的块里），搬到别人机器上是错的。
对方导入时重新走一遍导入流程，路径按他自己的机器生成——这样包才是真正可搬运的。

包的形状（一个 gzip 压缩的 tar）：

    课程标识.dtcourse
    ├── package.json     元数据：格式版本、标题、语言、来源、统计、打包时间
    ├── README.md        给人看的说明，说明这是什么、怎么导入
    └── course/          课程原始文件，与 data/user/courses/<标识>/ 下的内容一致

用 tar 而不是 zip，是因为课程里常有以点开头的文件和符号链接，tar 处理得更稳。
"""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import shutil
import tarfile
import tempfile
import time

from deeptutor_ext.course.service import CourseRecord, get_course_service
from deeptutor_ext.course.sources import SourceError, courses_root, slugify

logger = logging.getLogger(__name__)

PACKAGE_SUFFIX = ".dtcourse"
MANIFEST_NAME = "package.json"
CONTENT_DIR = "course"
# 包格式的版本。将来改了结构就往上加，导入时按它决定怎么读。
FORMAT_VERSION = 1

# 打包时不带上的东西：版本库元数据、依赖目录、各类缓存。它们又大又没用。
EXCLUDE_NAMES = {
    ".git", ".github", "node_modules", "__pycache__", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store", ".gocache",
}

# 超过这个大小就拒绝打包并说明原因。一门课打成几个 GB 传给别人是不现实的，
# 那种情况应该让对方自己从原始仓库导入。
MAX_PACKAGE_MB = 500


def _packages_dir() -> Path:
    """打好的包放哪。放在工作区下，不放课程目录——那里是原始资料。"""
    from deeptutor.services.path_service import get_path_service

    path = get_path_service().get_workspace_dir() / "course_packages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dir_size_mb(path: Path) -> float:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file() and not any(part in EXCLUDE_NAMES for part in entry.parts):
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return round(total / (1024 * 1024), 1)


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(info.name).name
    if name in EXCLUDE_NAMES:
        return None
    if any(part in EXCLUDE_NAMES for part in Path(info.name).parts):
        return None
    # 打包时抹掉属主信息：包要拿给别人用，带着本机的用户号没有意义。
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _readme(record: CourseRecord) -> str:
    stats = record.stats or {}
    return f"""# {record.title}

这是一个 DeepTutor 课程包。

| 项 | 值 |
|---|---|
| 课程标识 | `{record.slug}` |
| 原始来源 | {record.origin or "本地目录"} |
| 正文语言 | {record.language} |
| 规模 | {stats.get("chapters", 0)} 章 {stats.get("pages", 0)} 页，可运行代码段 {stats.get("runnable_cells", 0)} 个 |
| 打包时间 | {time.strftime("%Y-%m-%d %H:%M", time.localtime())} |

## 怎么导入

在 DeepTutor 的「课程」页选「从课程包导入」，把这个文件传上去即可。
导入后会在你自己的机器上重新生成课本，代码执行的路径也按你的机器生成。

包里只有课程的原始文件，不含课本与检索索引——那两样都带着打包那台机器的绝对路径，
搬过来是错的。导入时会重新生成，检索索引需要你自己点一次「建检索索引」。
"""


def export_course(slug: str) -> Path:
    """把一门课打成包，返回包文件的路径。"""
    service = get_course_service()
    record = service.get(slug)
    if record is None:
        raise SourceError(f"没有这门课：{slug}")

    source = courses_root() / record.slug
    if not source.is_dir():
        raise SourceError(f"课程目录不在了：{source}")

    size = _dir_size_mb(source)
    if size > MAX_PACKAGE_MB:
        raise SourceError(
            f"这门课有 {size} MB，超过了 {MAX_PACKAGE_MB} MB 的打包上限。"
            "这么大的课建议让对方直接从原始来源导入，而不是传包。"
        )

    target = _packages_dir() / f"{record.slug}{PACKAGE_SUFFIX}"
    manifest = {
        "format_version": FORMAT_VERSION,
        "exported_at": time.time(),
        "course": asdict(record) | {"book_id": "", "kb_name": "", "indexed_at": 0.0},
    }

    with tempfile.TemporaryDirectory() as staging:
        stage = Path(staging)
        (stage / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (stage / "README.md").write_text(_readme(record), encoding="utf-8")
        with tarfile.open(target, "w:gz") as tar:
            tar.add(stage / MANIFEST_NAME, arcname=MANIFEST_NAME)
            tar.add(stage / "README.md", arcname="README.md")
            tar.add(source, arcname=CONTENT_DIR, filter=_tar_filter)

    logger.info("课程 %s 已打包：%s（%.1f MB）", record.slug, target, target.stat().st_size / 1e6)
    return target


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """解包时逐个核对路径，挡住指向目录之外的条目。

    tar 里的路径是打包方写的，可能含 `..` 或绝对路径。不检查就等于让对方的包
    往我们机器的任意位置写文件。
    """
    dest = dest.resolve()
    for member in tar.getmembers():
        if member.issym() or member.islnk():
            # 符号链接可以指向目录外，课程内容也用不着它。
            continue
        target = (dest / member.name).resolve()
        if target != dest and dest not in target.parents:
            raise SourceError(f"包里有指向目录之外的路径，已拒绝：{member.name}")
        tar.extract(member, dest, filter="data")


def import_package(
    package_path: str | Path,
    *,
    slug: str = "",
    title: str = "",
    language: str = "",
    replace: bool = False,
) -> CourseRecord:
    """把一个课程包导进来，返回登记好的课程记录。"""
    package = Path(package_path).expanduser()
    if not package.is_file():
        raise SourceError(f"课程包不存在：{package}")
    if not tarfile.is_tarfile(package):
        raise SourceError("这不是一个课程包（应当是 .dtcourse 文件）。")

    with tempfile.TemporaryDirectory() as staging:
        stage = Path(staging)
        with tarfile.open(package, "r:gz") as tar:
            _safe_extract(tar, stage)

        manifest_path = stage / MANIFEST_NAME
        if not manifest_path.is_file():
            raise SourceError("课程包里没有 package.json，无法确认它是什么课。")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SourceError(f"课程包的元数据读不了：{exc}") from exc

        version = int(manifest.get("format_version") or 0)
        if version > FORMAT_VERSION:
            raise SourceError(
                f"这个包是格式版本 {version} 的，本机只认到 {FORMAT_VERSION}。请先升级 DeepTutor 扩展。"
            )

        packaged = manifest.get("course") or {}
        content = stage / CONTENT_DIR
        if not content.is_dir():
            raise SourceError("课程包里没有 course/ 目录，内容是空的。")

        resolved_slug = slugify(slug or packaged.get("slug") or package.stem)
        resolved_title = title or str(packaged.get("title") or resolved_slug)
        resolved_language = language or str(packaged.get("language") or "zh")

        target = courses_root() / resolved_slug
        if target.exists():
            if not replace:
                raise SourceError(
                    f"已经有一门叫 {resolved_slug} 的课了。要覆盖请选择覆盖，或换一个课程标识。"
                )
            shutil.rmtree(target)
        shutil.move(str(content), str(target))

    # 落地之后照常走导入流程：在本机重新生成课本，路径按本机算。
    record = get_course_service().create(
        str(target),
        title=resolved_title,
        slug=resolved_slug,
        language=resolved_language,
        replace=True,
    )
    logger.info("课程包已导入：%s", record.slug)
    return record


__all__ = [
    "MAX_PACKAGE_MB",
    "PACKAGE_SUFFIX",
    "export_course",
    "import_package",
]
