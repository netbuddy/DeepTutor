"""在某个模块被导入之后插一段自己的代码，而不改动那个模块的源文件。

为什么需要它：我们要往 DeepTutor 的内置工具清单里追加自己的工具，而那份清单是
``deeptutor.tools.builtin`` 模块顶层的一个元组，工具注册表在导入时就把它取走了。
想追加进去，就得赶在注册表读取之前、在该模块加载完成之后动手——正好是「导入后钩子」
要解决的问题。

Python 没有内建这个能力（PEP 369 提出过，被撤回了），标准做法是往 ``sys.meta_path``
放一个查找器：它对绝大多数模块一律放行，只在目标模块出现时，先让正常的查找流程拿到
加载器，再把加载器的 ``exec_module`` 包一层，在原逻辑执行完之后调用我们的回调。

这样做的好处是 DeepTutor 的源码一个字符都不用改，升级时不产生任何冲突。
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import logging
import sys
from typing import Callable

logger = logging.getLogger(__name__)


class _AfterImport(importlib.abc.MetaPathFinder):
    """只盯住一个模块名，等它加载完成后触发一次回调，然后自我摘除。"""

    def __init__(self, module_name: str, callback: Callable[[object], None]) -> None:
        self.module_name = module_name
        self.callback = callback

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.module_name:
            return None

        # 先把自己从查找链上摘掉，否则下面这次查找会再次落到自己身上，无限递归。
        self._detach()
        spec = importlib.util.find_spec(fullname)
        if spec is None or spec.loader is None:
            return None

        original_exec = spec.loader.exec_module
        callback = self.callback

        def exec_module(module):
            original_exec(module)
            try:
                callback(module)
            except Exception:
                # 钩子出问题不能连累宿主：DeepTutor 少了我们的工具还能正常跑，
                # 因为一个异常就起不来则是不可接受的。
                logger.exception("导入后钩子在处理 %s 时失败，已跳过", fullname)

        spec.loader.exec_module = exec_module
        return spec

    def _detach(self) -> None:
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass


def after_import(module_name: str, callback: Callable[[object], None]) -> None:
    """注册回调：*module_name* 加载完成后调用 *callback(module)*。

    如果该模块此刻已经在 ``sys.modules`` 里（说明我们来晚了），就立即调用回调，
    调用方不必区分这两种情况。
    """
    existing = sys.modules.get(module_name)
    if existing is not None:
        callback(existing)
        return
    sys.meta_path.insert(0, _AfterImport(module_name, callback))


__all__ = ["after_import"]
