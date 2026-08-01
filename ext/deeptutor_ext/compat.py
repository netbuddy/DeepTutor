"""绕开宿主环境里几处会误伤的第三方防护。

目前只有一处：nltk 新版本装了一个导入拦截器，凡是 nltk（直接或间接）要导入的模块，
只要解析出来的路径落在**当前工作目录之内**，就一律拒绝，理由是防止有人在工作目录
放一个同名文件劫持它。

这个判断在源码部署下会误伤：虚拟环境就建在项目目录里（``~/DeepTutor-src/.venv``），
而服务进程的工作目录正是项目根，于是 site-packages 里每一个正经的第三方库——比如
``regex``——都被判成「来自当前工作目录」，nltk 一用到就抛错。表现是建知识库直接失败，
错误信息还指向一个与实情无关的安全提示。

这里的做法不是把防护整个拆掉，而是给它开一条口子：路径确实在 site-packages 里的模块
直接放行，其余仍走原来的判断。真有人往工作目录扔同名文件，照样拦得住。
"""

from __future__ import annotations

import importlib.machinery
import logging
from pathlib import Path
import site
import sys

logger = logging.getLogger(__name__)

_patched = False


def _site_package_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in site.getsitepackages() + [site.getusersitepackages()]:
        try:
            path = Path(candidate).resolve()
        except (OSError, RuntimeError):
            continue
        if path.is_dir():
            roots.append(path)
    return roots


def _inside(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def relax_nltk_cwd_guard(_module=None) -> None:
    """让 nltk 的导入拦截器放行 site-packages 里的模块。可以重复调用。"""
    global _patched
    if _patched:
        return

    finders = [f for f in sys.meta_path if type(f).__name__ == "NLTKSafeImportFinder"]
    if not finders:
        return

    roots = _site_package_roots()
    if not roots:
        return

    for finder in finders:
        original = finder.find_spec

        def find_spec(fullname, path, target=None, _original=original):
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is not None and spec.origin:
                try:
                    if _inside(Path(spec.origin).resolve(), roots):
                        return None  # 正经安装的第三方库，放行
                except (OSError, RuntimeError):
                    pass
            return _original(fullname, path, target)

        finder.find_spec = find_spec

    _patched = True
    logger.info("已放宽 nltk 的工作目录导入拦截：site-packages 内的模块不再被误拦")


__all__ = ["relax_nltk_cwd_guard"]
