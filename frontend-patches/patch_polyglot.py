#!/usr/bin/env python3
"""把 JavaScript / TypeScript / Rust 接进可运行的代码格。在 ~/DeepTutor-ext 下执行。

之前只有 python 和 go 能跑，写 ```js 只做语法高亮。这三种语言都没有长驻内核，
执行语义和 Go 一样是「把这一页到当前格为止的代码凑齐，一起跑」，
具体怎么凑见 kernel/polyglot.py 的模块说明。
"""

from pathlib import Path

LAYOUTS = Path("deeptutor_ext/course/layouts.py")
API = Path("deeptutor_ext/api.py")
KERNEL_INIT = Path("deeptutor_ext/kernel/__init__.py")

# ── layouts.py：多认几种语言 ─────────────────────────────────────────

LANGS_OLD = '_RUNNABLE_LANGS = {"py", "python", "python3", "go", "golang"}'
LANGS_NEW = '''_RUNNABLE_LANGS = {
    "py", "python", "python3",
    "go", "golang",
    "js", "javascript", "node", "mjs",
    "ts", "typescript",
    "rs", "rust",
}'''

# Rust 的展示型片段（引用别处定义做对比、没有任何顶层项）也会编译失败，
# 但判据不像 Go 那样有 package 声明可依。这里只挡明显不是完整代码的：
# 整段没有任何 fn / struct / enum / impl / use / let 开头的行。
RUST_GUARD_OLD = '''            if language in ("go", "golang") and not re.search(r"^\\s*package\\s+\\w", code, re.M):'''
RUST_GUARD_NEW = '''            if language in ("rs", "rust") and not re.search(
                r"^\\s*(?:pub\\s+)?(?:fn|struct|enum|impl|trait|use|mod|const|static|type)\\b",
                code,
                re.M,
            ):
                # 讲义里引用别处定义做对比的 Rust 片段没有任何顶层项，
                # 当作可运行会直接编译失败——那不是学生的错。
                runnable = False
            if language in ("go", "golang") and not re.search(r"^\\s*package\\s+\\w", code, re.M):'''

# ── kernel/__init__.py：导出新模块 ──────────────────────────────────

KERNEL_EXPORT_OLD = "from deeptutor_ext.kernel.golang import build_runner_snippet"
KERNEL_EXPORT_NEW = '''from deeptutor_ext.kernel.polyglot import (
    build_node_snippet,
    build_rust_snippet,
    concat_rust,
    concat_script,
    looks_like_js,
    looks_like_rust,
    looks_like_ts,
)
from deeptutor_ext.kernel.golang import build_runner_snippet'''

# ── api.py：分派 ────────────────────────────────────────────────────

DISPATCH_OLD = """    block = page.block_by_id(body.block_id)
    if block is not None and _block_language(block) in ("go", "golang"):
        snippet = _go_snippet(page, body.block_id, body.code, session_key)"""

DISPATCH_NEW = '''    block = page.block_by_id(body.block_id)
    language = _block_language(block) if block is not None else ""

    # JS / TS / Rust 和 Go 一样没有长驻内核，走「凑齐到这一格再跑」那条路。
    if block is not None and language in _CONCAT_LANGS:
        snippet = _concat_snippet(page, body.block_id, body.code, session_key, language)
        try:
            result = await manager.execute(
                session_key, snippet, cwd=cwd, timeout_s=body.timeout_s or 180
            )
        except KernelUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        payload = result.to_dict()
        payload["block_id"] = body.block_id
        payload["language"] = language
        payload["preceding"] = []
        return payload

    if block is not None and language in ("go", "golang"):
        snippet = _go_snippet(page, body.block_id, body.code, session_key)'''

HELPER = '''_CONCAT_LANGS = {"js", "javascript", "node", "mjs", "ts", "typescript", "rs", "rust"}


def _concat_snippet(
    page, target_block_id: str, override_code: str, session_key: str, language: str
) -> str:
    """把这一页到目标格为止的同语言代码凑齐，生成一段跑它的 Python。

    和 Go 那条路的区别只在「怎么凑」：Go 是多文件同包编译，这里是拼成一份源码。
    拼接的理由与代价写在 kernel/polyglot.py 的模块说明里。
    """
    from deeptutor_ext.kernel import (
        build_node_snippet,
        build_rust_snippet,
        concat_rust,
        concat_script,
    )

    cells: list[str] = []
    for block in _runnable_blocks(page):
        if _block_language(block) != language:
            continue
        code = str((block.payload or {}).get("code") or "")
        if block.id == target_block_id and override_code.strip():
            code = override_code
        if code.strip():
            cells.append(code)
        if block.id == target_block_id:
            break

    if not cells:
        raise HTTPException(status_code=400, detail="这一页没有可运行的这种语言的代码。")

    from deeptutor.services.path_service import get_path_service

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_key)[:64]
    work_dir = str(
        get_path_service().get_task_workspace("chat", f"notebook_{safe}") / f"{language}_work"
    )

    if language in ("rs", "rust"):
        source, runnable = concat_rust(cells)
        return build_rust_snippet(source, work_dir=work_dir, runnable=runnable)
    return build_node_snippet(
        concat_script(cells),
        work_dir=work_dir,
        typescript=language in ("ts", "typescript"),
    )


def _go_snippet('''


def patch(path: Path, pairs, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in text:
            continue
        if old not in text:
            print(f"{label} 里没找到片段：{old[:70]}…")
            return False
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    if not patch(LAYOUTS, [(LANGS_OLD, LANGS_NEW), (RUST_GUARD_OLD, RUST_GUARD_NEW)], "layouts.py"):
        return 1
    if not patch(KERNEL_INIT, [(KERNEL_EXPORT_OLD, KERNEL_EXPORT_NEW)], "kernel/__init__.py"):
        return 1
    if not patch(API, [("def _go_snippet(", HELPER), (DISPATCH_OLD, DISPATCH_NEW)], "api.py"):
        return 1
    print("JavaScript / TypeScript / Rust 已接进可运行的代码格。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
