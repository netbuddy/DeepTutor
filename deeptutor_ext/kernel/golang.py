"""在同一个容器里跑 Go 代码。

Python 那边靠一个长驻内核保持状态：前面格子定义的变量，后面格子直接能用。
Go 没有这回事——它是编译型语言，一段代码要能跑，它依赖的类型和函数必须在同一次
编译里全都在场。所以 Go 格子的执行语义只能是「把这一页到这里为止的所有代码凑齐，
一起编译，再运行」。

这也正好对上课程的教学路径：第一章写类型定义，第二章写事件流，第三章写主循环，
每一章都是往同一个模块里添一个文件，跑起来的是累积到当前为止的完整程序。

实现上不另开通道——把 Go 的编译与运行包成一小段 Python，交给已有的内核去执行。
好处是输出收集、超时、产物落盘这些全都沿用现成的，不必再写一遍。
"""

from __future__ import annotations

import json
import re

# 从 `package xxx` 那一行认出包名。教学代码基本都是 main 包。
_PACKAGE = re.compile(r"^\s*package\s+([A-Za-z_]\w*)", re.M)
# 从注释里认出这一格希望写成哪个文件，写法是首行 `// file: types.go`。
_FILENAME_HINT = re.compile(r"^\s*//\s*file:\s*([\w./-]+\.go)\s*$", re.M)


def looks_like_go(language: str) -> bool:
    return (language or "").strip().lower() in {"go", "golang"}


def filename_for(code: str, index: int) -> str:
    """这一格的代码该写成哪个文件。

    优先用代码里 `// file: xxx.go` 的声明——课程里靠它把同一个类型的定义固定在同一个
    文件上，学生反复运行不会积出一堆重复定义。没写就按格号生成一个稳定的名字。
    """
    hint = _FILENAME_HINT.search(code or "")
    if hint:
        name = hint.group(1).strip().lstrip("/")
        return name if name.endswith(".go") else f"{name}.go"
    return f"cell{index:02d}.go"


def has_main(code: str) -> bool:
    return bool(re.search(r"^\s*func\s+main\s*\(\s*\)", code or "", re.M))


def build_runner_snippet(
    files: dict[str, str],
    *,
    module_dir: str,
    module_name: str = "lesson",
    runnable: bool,
    go_timeout_s: int = 120,
) -> str:
    """生成一段 Python，把 *files* 写进模块目录并编译运行。

    这段代码会被交给容器里的 Python 内核执行，所以它只能用标准库。
    输出直接打印，让上层沿用既有的输出收集逻辑。

    *runnable* 为假时只编译不运行——课程里那些「只定义类型、还没有 main」的章节，
    编译通过本身就是这一步的验收结果。
    """
    payload = json.dumps(files, ensure_ascii=False)
    return f'''
import json, os, pathlib, shutil, subprocess, sys

_dir = pathlib.Path({module_dir!r})
_dir.mkdir(parents=True, exist_ok=True)

# 先清掉上一次留下的 .go 文件：课程改过文件名时，旧文件留着会造成重复定义，
# 报错信息还指向学生根本没看到的代码。
for _stale in _dir.glob("*.go"):
    _stale.unlink()

for _name, _content in json.loads({payload!r}).items():
    _target = _dir / _name
    _target.parent.mkdir(parents=True, exist_ok=True)
    _target.write_text(_content, encoding="utf-8")

if not (_dir / "go.mod").exists():
    subprocess.run(
        ["go", "mod", "init", {module_name!r}],
        cwd=_dir, capture_output=True, text=True, timeout=60,
    )

# 没有 main 函数时不能用 go build——main 包缺 main 会被判成错误，而课程里
# 「这一章只定义类型」是完全正常的一步。go vet 做的是类型检查，不要求可链接。
_cmd = ["go", "run", "."] if {runnable!r} else ["go", "vet", "./..."]
try:
    _proc = subprocess.run(
        _cmd, cwd=_dir, capture_output=True, text=True, timeout={go_timeout_s},
    )
except subprocess.TimeoutExpired:
    print("Go 程序超过 {go_timeout_s} 秒还没结束，已中断。", file=sys.stderr)
else:
    if _proc.stdout:
        print(_proc.stdout, end="")
    if _proc.stderr:
        print(_proc.stderr, end="", file=sys.stderr)
    if _proc.returncode != 0:
        print(f"\\n（go 退出码 {{_proc.returncode}}）", file=sys.stderr)
    elif not {runnable!r}:
        print("编译通过。这一节还没有 main 函数，所以只做编译检查。")
'''.strip()


__all__ = ["build_runner_snippet", "filename_for", "has_main", "looks_like_go"]
