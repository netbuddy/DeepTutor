"""唯一的接入点：把扩展工具挂进 DeepTutor 的内置工具清单。

DeepTutor 的工具注册表在导入 ``deeptutor.tools.builtin`` 时，就把该模块顶层的
``BUILTIN_TOOL_TYPES`` 元组取走了。所以我们在那个模块加载完成的瞬间往元组里追加
自己的工具类，注册表随后读到的就是加好的版本。此外还要往
``CONFIGURABLE_BUILTIN_TOOL_NAMES`` 里登记名字，对话流程才会在合适的时机把工具
挂给模型。

整个过程不改 DeepTutor 的任何源文件，所以升级时不会产生冲突；代价是每次升级后
要确认这两个名字还在（DeepTutor 改了内部结构的话，这里会静默失效）。
``make verify`` 就是为此准备的。
"""

from __future__ import annotations

import logging

from deeptutor_ext._hook import after_import
from deeptutor_ext.tools.ext_status import ExtStatusTool

logger = logging.getLogger(__name__)

# 扩展提供的全部工具类。新增工具时只改这一处。
EXTENSION_TOOL_TYPES = (ExtStatusTool,)

# 其中哪些允许对话流程自动挂载给模型。留空表示只能在 Playground 里手工调用。
AUTO_MOUNTED_TOOL_NAMES = ("ext_status",)

_installed = False


def _extend_builtin_tools(module) -> None:
    """在 ``deeptutor.tools.builtin`` 加载完成后追加我们的工具。"""
    existing = set(getattr(module, "BUILTIN_TOOL_NAMES", ()))
    added = []
    for tool_type in EXTENSION_TOOL_TYPES:
        name = tool_type().name
        if name in existing:
            continue
        module.BUILTIN_TOOL_TYPES = tuple(module.BUILTIN_TOOL_TYPES) + (tool_type,)
        added.append(name)

    if not added:
        return

    module.BUILTIN_TOOL_NAMES = tuple(t().name for t in module.BUILTIN_TOOL_TYPES)
    mountable = tuple(n for n in AUTO_MOUNTED_TOOL_NAMES if n in added)
    if mountable:
        module.CONFIGURABLE_BUILTIN_TOOL_NAMES = (
            tuple(module.CONFIGURABLE_BUILTIN_TOOL_NAMES) + mountable
        )
    logger.info("扩展工具已接入：%s", "、".join(added))


def _attach_api_routes(module) -> None:
    """在宿主的 FastAPI 应用装配完成后追加我们的接口。"""
    app = getattr(module, "app", None)
    if app is None:
        logger.warning("宿主的 api.main 里没有 app 对象，扩展接口未挂载")
        return
    from deeptutor_ext.api import attach

    attach(app)


def install() -> None:
    """登记接入动作。可以重复调用，只有第一次生效。"""
    global _installed
    if _installed:
        return
    _installed = True
    after_import("deeptutor.tools.builtin", _extend_builtin_tools)
    after_import("deeptutor.api.main", _attach_api_routes)


__all__ = ["install", "EXTENSION_TOOL_TYPES", "AUTO_MOUNTED_TOOL_NAMES"]
