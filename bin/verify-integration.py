#!/usr/bin/env python3
"""升级后的接入自检：确认扩展仍然挂在 DeepTutor 上，并确认沙箱真的能跑。

为什么必须有这一步：扩展是靠站点钩子挂进宿主的内置工具清单的，一旦 DeepTutor
改了那份清单的名字或位置，接入会**静默失效**——工具只是不出现，界面上看不出
任何异常，等到学生问「怎么跑不了代码」才发现。所以每次升级后都要跑一遍这个脚本，
把接入契约逐条对照一遍。

沙箱那一项是单独查的，因为 DeepTutor 自带的健康探针只看返回结构里的 error 字段，
而 bubblewrap 失败时是「进程正常退出、退出码非零、错误在标准错误里」，error 是空的，
探针会误报健康。这里改为真跑一条命令看退出码。

用法：<DeepTutor 虚拟环境的 python> bin/verify-integration.py
退出码 0 表示全部通过，非 0 表示有检查项失败。
"""

from __future__ import annotations

import asyncio
import site
import sys
from pathlib import Path

PASS = "✓"
FAIL = "✗"

results: list[tuple[bool, str, str]] = []


def check(ok: bool, title: str, detail: str = "") -> None:
    results.append((ok, title, detail))


def check_sitehook() -> None:
    """站点钩子文件必须在虚拟环境里，否则任何入口都不会加载扩展。"""
    found = [
        Path(d) / "deeptutor_ext.pth"
        for d in site.getsitepackages()
        if (Path(d) / "deeptutor_ext.pth").exists()
    ]
    check(
        bool(found),
        "站点钩子已安装",
        str(found[0]) if found else "缺少 deeptutor_ext.pth，请重新执行 bin/install-sitehook.py",
    )


def check_host_contract() -> None:
    """逐条核对我们依赖的宿主符号是否还在。这些就是接入契约。"""
    try:
        from deeptutor.tools import builtin
    except Exception as exc:
        check(False, "能导入 deeptutor.tools.builtin", f"{type(exc).__name__}: {exc}")
        return

    for attr in ("BUILTIN_TOOL_TYPES", "BUILTIN_TOOL_NAMES", "CONFIGURABLE_BUILTIN_TOOL_NAMES"):
        check(
            hasattr(builtin, attr),
            f"宿主仍有 {attr}",
            "" if hasattr(builtin, attr) else "上游改名或移除了这个符号，接入点需要跟着改",
        )

    try:
        from deeptutor.runtime.registry.tool_registry import ToolRegistry

        check(
            callable(getattr(ToolRegistry, "load_builtins", None))
            and callable(getattr(ToolRegistry, "register", None)),
            "宿主的工具注册表接口未变",
        )
    except Exception as exc:
        check(False, "能导入宿主的工具注册表", f"{type(exc).__name__}: {exc}")


def check_tools_registered() -> None:
    """扩展工具必须真的出现在注册表里，并且能被模型看见。"""
    try:
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        from deeptutor_ext.integrate import AUTO_MOUNTED_TOOL_NAMES, EXTENSION_TOOL_TYPES
    except Exception as exc:
        check(False, "能导入扩展与注册表", f"{type(exc).__name__}: {exc}")
        return

    registry = get_tool_registry()
    registered = set(registry.list_tools())
    expected = [tool_type().name for tool_type in EXTENSION_TOOL_TYPES]
    missing = [name for name in expected if name not in registered]
    check(
        not missing,
        f"{len(expected)} 个扩展工具都在注册表里",
        "缺失：" + "、".join(missing) if missing else "、".join(expected),
    )

    from deeptutor.tools.builtin import CONFIGURABLE_BUILTIN_TOOL_NAMES

    not_mountable = [n for n in AUTO_MOUNTED_TOOL_NAMES if n not in CONFIGURABLE_BUILTIN_TOOL_NAMES]
    check(
        not not_mountable,
        "该自动挂载的工具都已登记",
        "未登记：" + "、".join(not_mountable) if not_mountable else "",
    )


def check_nltk_guard() -> None:
    """nltk 的工作目录拦截器在源码部署下会误伤，确认放宽补丁生效。"""
    try:
        import nltk  # noqa: F401  触发拦截器安装
        import sys

        from deeptutor_ext.compat import relax_nltk_cwd_guard

        relax_nltk_cwd_guard()
        has_finder = any(type(f).__name__ == "NLTKSafeImportFinder" for f in sys.meta_path)
        if not has_finder:
            check(True, "nltk 没有装工作目录拦截器", "这个版本不需要放宽")
            return
        import importlib

        importlib.import_module("regex")
        check(True, "nltk 的工作目录拦截已放宽", "site-packages 里的库能正常导入")
    except ImportError as exc:
        check(False, "nltk 的工作目录拦截已放宽", f"仍被拦：{exc}")
    except Exception as exc:
        check(False, "nltk 的工作目录拦截已放宽", f"{type(exc).__name__}: {exc}")


def check_sandbox() -> None:
    """真跑一条命令，而不是信宿主那个只看 error 字段的探针。"""
    try:
        from deeptutor.services.sandbox import ExecRequest, ResourceLimits, get_sandbox_service
    except Exception as exc:
        check(False, "能导入沙箱服务", f"{type(exc).__name__}: {exc}")
        return

    async def probe():
        service = get_sandbox_service()
        level = await service.isolation_level()
        result = await service.run(
            ExecRequest(command="echo sandbox-ok", limits=ResourceLimits(timeout_s=15)),
            user_id="verify",
        )
        return level, result

    level, result = asyncio.run(probe())
    really_works = result.exit_code == 0 and "sandbox-ok" in (result.stdout or "")
    detail = f"隔离等级 {level.value}"
    if not really_works:
        first_line = (result.stderr or result.stdout or result.error or "").strip().splitlines()
        detail += "；实际执行失败：" + (first_line[0] if first_line else "无输出")
    check(really_works, "沙箱能真的执行命令", detail)


def main() -> int:
    check_sitehook()
    check_host_contract()
    check_tools_registered()
    check_nltk_guard()
    check_sandbox()

    try:
        from deeptutor.__version__ import __version__ as host_version
    except Exception:
        host_version = "未知"
    from deeptutor_ext import __version__ as ext_version

    print(f"宿主 DeepTutor {host_version} · 扩展 {ext_version}")
    print("-" * 56)
    failed = 0
    for ok, title, detail in results:
        mark = PASS if ok else FAIL
        line = f"{mark} {title}"
        if detail:
            line += f"  —  {detail}"
        print(line)
        if not ok:
            failed += 1
    print("-" * 56)
    if failed:
        print(f"{failed} 项未通过。接入可能已经失效，先修好再启动服务。")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
