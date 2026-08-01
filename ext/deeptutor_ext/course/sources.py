"""把「用户给的一个来源」变成课程目录下的一份本地内容。

用户手里的课程可能是一个 Git 仓库地址、一个本地目录，也可能只是一个压缩包。不管哪种，
最终都要落到 ``data/user/courses/<课程标识>/`` 下——那是执行容器唯一挂到的目录（只读），
课程不在那里，页面能显示但代码跑不起来。

克隆一律用浅克隆并且不取子模块：课程仓库往往带着几十种语言的翻译和历史插图，
完整历史动辄上 GB，而学习只需要当前这一份。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"[^a-z0-9]+")
# 克隆一个大课程仓库可能要几分钟，但也不能无限等。
_CLONE_TIMEOUT_S = 900


class SourceError(RuntimeError):
    """来源取不下来。消息面向使用者，可以直接显示。"""


@dataclass
class FetchedSource:
    """取回来的课程内容。"""

    slug: str
    path: Path
    kind: str  # "git" | "local"
    origin: str  # 用户当初给的那个地址或路径
    size_mb: float


def slugify(value: str) -> str:
    cleaned = _SLUG.sub("-", value.strip().lower()).strip("-")
    return (cleaned or "course")[:48]


def courses_root() -> Path:
    from deeptutor.services.path_service import get_path_service

    root = get_path_service().get_public_outputs_root() / "courses"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dir_size_mb(path: Path) -> float:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return round(total / (1024 * 1024), 1)


def _run_git(args: list[str], cwd: Path | None = None) -> None:
    env = dict(os.environ)
    # 别在这里卡着等用户名密码：私有仓库直接失败，比挂住好。
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=_CLONE_TIMEOUT_S,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"取课程超时（{_CLONE_TIMEOUT_S} 秒）。仓库可能太大或网络不通。") from exc
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        reason = tail[-1] if tail else f"git 退出码 {result.returncode}"
        raise SourceError(f"取课程失败：{reason}")


def is_git_url(value: str) -> bool:
    value = value.strip()
    return value.startswith(("http://", "https://", "git@", "ssh://")) and (
        value.endswith(".git") or "github.com" in value or "gitlab" in value or "gitee" in value
    )


def fetch(origin: str, *, slug: str = "", branch: str = "", replace: bool = False) -> FetchedSource:
    """把 *origin* 取到课程目录下，返回落地信息。

    *origin* 可以是 Git 地址，也可以是本机上的一个目录（会被复制过来，
    因为容器只挂课程目录，原地引用它看不到）。
    """
    origin = origin.strip()
    if not origin:
        raise SourceError("请给出课程来源：一个 Git 仓库地址，或本机上的一个目录。")

    if is_git_url(origin):
        name = slug or slugify(Path(origin.rstrip("/")).name.removesuffix(".git"))
        target = courses_root() / name
        if target.exists():
            if not replace:
                raise SourceError(
                    f"课程目录 {name} 已经存在。要重新取请选择覆盖，或换一个课程标识。"
                )
            shutil.rmtree(target)
        args = ["clone", "--depth", "1", "--recurse-submodules=no"]
        if branch:
            args += ["--branch", branch]
        args += [origin, str(target)]
        _run_git(args)
        logger.info("课程已克隆到 %s", target)
        return FetchedSource(
            slug=name, path=target, kind="git", origin=origin, size_mb=_dir_size_mb(target)
        )

    source_path = Path(origin).expanduser().resolve()
    if not source_path.is_dir():
        raise SourceError(f"这既不是 Git 地址，也不是本机上的目录：{origin}")

    name = slug or slugify(source_path.name)
    target = courses_root() / name
    if source_path == target:
        return FetchedSource(
            slug=name, path=target, kind="local", origin=origin, size_mb=_dir_size_mb(target)
        )
    if target.exists():
        if not replace:
            raise SourceError(f"课程目录 {name} 已经存在。要重新导入请选择覆盖。")
        shutil.rmtree(target)
    shutil.copytree(source_path, target, symlinks=False, ignore=shutil.ignore_patterns(".git"))
    logger.info("课程已复制到 %s", target)
    return FetchedSource(
        slug=name, path=target, kind="local", origin=origin, size_mb=_dir_size_mb(target)
    )


def remove(slug: str) -> bool:
    """删掉课程目录。返回是否真的删了东西。"""
    target = courses_root() / slugify(slug)
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


__all__ = ["FetchedSource", "SourceError", "courses_root", "fetch", "is_git_url", "remove", "slugify"]
