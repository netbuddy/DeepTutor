"""在同一个容器里跑 JavaScript、TypeScript 和 Rust 代码。

和 Go 那边（``golang.py``）是同一个思路：这几种语言都没有长驻内核，
执行语义只能是「把这一页到当前格为止的代码凑齐，一起跑」。区别在于凑的方式：

* **Go** 是多文件同包编译，所以按 ``// file: xxx.go`` 分文件、一起编译。
* **JavaScript / TypeScript** 拼成一个脚本。选拼接而不是分模块，是为了让
  前面格子定义的变量在后面格子里还能用——那是学生对「一格一格往下跑」的预期。
  代价是同名变量不能重复声明（见 ``concat_script`` 的说明）。
* **Rust** 也拼成一个文件，但要处理 ``fn main``：前面各格的 main 会被摘掉，
  只留当前格的那个。规则是「前面各格的定义都在场，只有当前格的 main 会执行」。

实现上不另开通道——把编译与运行包成一小段 Python，交给已有的内核去执行。
输出收集、超时、产物落盘全都沿用现成的。
"""

from __future__ import annotations

import re

JS_LANGS = {"js", "javascript", "node", "mjs"}
TS_LANGS = {"ts", "typescript"}
RUST_LANGS = {"rs", "rust"}


def looks_like_js(language: str) -> bool:
    return (language or "").strip().lower() in JS_LANGS


def looks_like_ts(language: str) -> bool:
    return (language or "").strip().lower() in TS_LANGS


def looks_like_rust(language: str) -> bool:
    return (language or "").strip().lower() in RUST_LANGS


def concat_script(cells: list[str]) -> str:
    """把若干格拼成一个脚本。

    每格之间插一行注释做分隔，报错时的行号能对上是哪一格。

    **这里有一条要写进讲义的约束**：拼接之后是同一个作用域，
    所以两格里不能都写 ``const x = ...``。Python 那边重复赋值没问题，
    JS 会直接报 SyntaxError。讲义里同一个名字要么只声明一次，
    要么后面改用赋值。
    """
    parts: list[str] = []
    for index, code in enumerate(cells, start=1):
        parts.append(f"// ── 第 {index} 格 ──")
        parts.append(code.rstrip())
    return "\n".join(parts) + "\n"


# ── Rust：摘掉前面各格的 main ────────────────────────────────────────

_RUST_MAIN = re.compile(r"^\s*(?:pub\s+)?fn\s+main\s*\(\s*\)\s*(?:->[^{]*)?\{", re.M)


def strip_main(code: str) -> str:
    """摘掉一段 Rust 代码里的 ``fn main`` 函数体，其余原样保留。

    用大括号配对来找函数结尾，不用正则匹配整个函数——函数体里有嵌套大括号，
    正则做不到。字符串字面量里的大括号会被误算，但教学代码里
    ``fn main`` 里出现不成对的大括号字面量是极少数，先不处理，
    真遇到了会表现为编译报错而不是静默出错。
    """
    match = _RUST_MAIN.search(code)
    if not match:
        return code
    start = match.start()
    depth = 0
    index = code.index("{", match.start())
    for pos in range(index, len(code)):
        if code[pos] == "{":
            depth += 1
        elif code[pos] == "}":
            depth -= 1
            if depth == 0:
                return (code[:start] + code[pos + 1 :]).strip() + "\n"
    return code[:start].strip() + "\n"


def has_rust_main(code: str) -> bool:
    return bool(_RUST_MAIN.search(code or ""))


def concat_rust(cells: list[str]) -> tuple[str, bool]:
    """把若干格拼成一个 main.rs，返回（源码，最后一格有没有 main）。

    前面各格的 main 被摘掉，当前格的留着。没有任何 main 时只做编译检查——
    课程里「这一章只定义类型」是正常的一步。
    """
    if not cells:
        return "", False
    body: list[str] = []
    for index, code in enumerate(cells, start=1):
        is_last = index == len(cells)
        body.append(f"// ── 第 {index} 格 ──")
        body.append((code if is_last else strip_main(code)).rstrip())
    runnable = has_rust_main(cells[-1])
    return "\n".join(body) + "\n", runnable


# ── 生成交给内核执行的那段 Python ────────────────────────────────────


def build_node_snippet(
    script: str,
    *,
    work_dir: str,
    typescript: bool = False,
    timeout_s: int = 120,
) -> str:
    """生成一段 Python，把脚本写进工作目录并交给 node 执行。

    TypeScript 走 Node 自带的类型剥离（``--experimental-strip-types``），
    不额外装编译器。它只剥类型、不做类型检查——对课程够用，
    而且省掉一个几十兆的依赖和一次编译等待。
    """
    suffix = "ts" if typescript else "js"
    flags = ["--experimental-strip-types"] if typescript else []
    return f'''
import os, pathlib, subprocess, sys

_dir = pathlib.Path({work_dir!r})
_dir.mkdir(parents=True, exist_ok=True)
_entry = _dir / "lesson.{suffix}"
_entry.write_text({script!r}, encoding="utf-8")

_cmd = ["node", *{flags!r}, str(_entry)]
# 关掉终端颜色：node 默认给数字加 ANSI 颜色码，页面上会显示成一串乱码。
_env = {{**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}}
try:
    _proc = subprocess.run(
        _cmd, cwd=_dir, capture_output=True, text=True, timeout={timeout_s}, env=_env,
    )
except FileNotFoundError:
    print("这个容器里没有 node。重建内核镜像：cd ~/DeepTutor-ext && make kernel-build",
          file=sys.stderr)
except subprocess.TimeoutExpired:
    print("程序超过 {timeout_s} 秒还没结束，已中断。", file=sys.stderr)
else:
    if _proc.stdout:
        print(_proc.stdout, end="")
    if _proc.stderr:
        print(_proc.stderr, end="", file=sys.stderr)
    if _proc.returncode != 0:
        print(f"\\n（node 退出码 {{_proc.returncode}}）", file=sys.stderr)
'''.strip()


def build_rust_snippet(
    source: str,
    *,
    work_dir: str,
    runnable: bool,
    timeout_s: int = 180,
) -> str:
    """生成一段 Python，把源码写进工作目录，用 rustc 编译（并运行）。

    用 rustc 直接编译单文件，不建 cargo 工程：课程代码不依赖外部 crate，
    省掉 cargo 的目录结构和一次网络解析。

    没有 main 时用 ``--emit=metadata`` 只做检查不产出可执行文件——
    对应 Go 那边的 ``go vet``。
    """
    return f'''
import pathlib, subprocess, sys

_dir = pathlib.Path({work_dir!r})
_dir.mkdir(parents=True, exist_ok=True)
_src = _dir / "main.rs"
_src.write_text({source!r}, encoding="utf-8")
_bin = _dir / "lesson"

_runnable = {runnable!r}
_compile = ["rustc", "--edition", "2021"]
if _runnable:
    _compile += [str(_src), "-o", str(_bin)]
else:
    # 没有 main：只做类型检查，不要求能链接成可执行文件。
    _compile += ["--emit=metadata", "--crate-type", "lib", str(_src),
                 "-o", str(_dir / "lesson.rmeta")]

try:
    _proc = subprocess.run(
        _compile, cwd=_dir, capture_output=True, text=True, timeout={timeout_s},
    )
except FileNotFoundError:
    print("这个容器里没有 rustc。重建内核镜像：cd ~/DeepTutor-ext && make kernel-build",
          file=sys.stderr)
except subprocess.TimeoutExpired:
    print("编译超过 {timeout_s} 秒还没结束，已中断。", file=sys.stderr)
else:
    if _proc.stderr:
        print(_proc.stderr, end="", file=sys.stderr)
    if _proc.returncode != 0:
        print(f"\\n（rustc 退出码 {{_proc.returncode}}）", file=sys.stderr)
    elif not _runnable:
        print("编译通过。这一节还没有 main 函数，所以只做编译检查。")
    else:
        try:
            _run = subprocess.run(
                [str(_bin)], cwd=_dir, capture_output=True, text=True,
                timeout={timeout_s},
            )
        except subprocess.TimeoutExpired:
            print("程序超过 {timeout_s} 秒还没结束，已中断。", file=sys.stderr)
        else:
            if _run.stdout:
                print(_run.stdout, end="")
            if _run.stderr:
                print(_run.stderr, end="", file=sys.stderr)
            if _run.returncode != 0:
                print(f"\\n（程序退出码 {{_run.returncode}}）", file=sys.stderr)
'''.strip()


__all__ = [
    "JS_LANGS",
    "RUST_LANGS",
    "TS_LANGS",
    "build_node_snippet",
    "build_rust_snippet",
    "concat_rust",
    "concat_script",
    "has_rust_main",
    "looks_like_js",
    "looks_like_rust",
    "looks_like_ts",
    "strip_main",
]
