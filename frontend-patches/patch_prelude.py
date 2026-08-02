#!/usr/bin/env python3
"""让讲义不必每章开头重贴两百行累积代码。在 ~/DeepTutor-ext 下执行。

问题：一页一个全新内核，所以每章开头都要把前面所有章的成果再贴一遍。实测这一格
占了全课代码量的 41%，还把「这一章新写了什么」埋在两百行里。

两种语言各配一条通道，讲义里只留一两行：

* **Python**：课程目录里放 ``chapters/zh/agentlib.py``（或 ``agentlib/`` 包）。
  内核切工作目录时，把 cwd 及其上溯三层一起加进 ``sys.path``，学生写
  ``from agentlib import *`` 就能拿到前面章节的全部成果。
  上溯三层是因为工作目录是 ``courses/<课>/chapters/zh/partN``，
  库放在 ``chapters/zh/`` 这一层最自然，放课程根也照样能找到。

* **Go**：每部分目录下放 ``_prelude/``，里面是若干 ``.go`` 文件。累积编译时先把
  它们铺进编译目录，再叠上本页各格。讲义里因此不用出现 core.go 那一大坨。
  同名文件以页面里的为准——学生想覆盖某个铺底文件时，写一个同名的格子就行。
"""

from pathlib import Path

SESSION = Path("deeptutor_ext/kernel/session.py")
API = Path("deeptutor_ext/api.py")

# ── Python：把课程目录加进 sys.path ───────────────────────────────────

CHDIR_OLD = '''    async def _chdir(self, session: KernelSession, cwd: str) -> None:
        """把内核的工作目录切到 *cwd*。课程代码全用相对路径，这一步不能省。"""
        code = f"import os\\nos.chdir({cwd!r})"'''

CHDIR_NEW = '''    async def _chdir(self, session: KernelSession, cwd: str) -> None:
        """把内核的工作目录切到 *cwd*，并让课程自带的库可以被 import。

        课程代码全用相对路径，切目录这一步不能省。

        顺带把 cwd 及其上溯三层加进 ``sys.path``：讲义每章开头本来要重贴两百行
        累积代码，有了这条通道就可以把它们收进课程目录里的一个 ``agentlib``，
        讲义只写一行 ``from agentlib import *``。上溯三层是因为工作目录形如
        ``courses/<课>/chapters/zh/partN``，库放在 ``chapters/zh/`` 或课程根
        都能被找到。
        """
        code = (
            "import os, sys\\n"
            f"os.chdir({cwd!r})\\n"
            "_here = os.getcwd()\\n"
            "for _ in range(4):\\n"
            "    if _here not in sys.path:\\n"
            "        sys.path.insert(0, _here)\\n"
            "    _parent = os.path.dirname(_here)\\n"
            "    if _parent == _here:\\n"
            "        break\\n"
            "    _here = _parent\\n"
            "del _here, _parent\\n"
        )'''

# ── Go：编译前先铺 _prelude ──────────────────────────────────────────

GO_OLD = """    files: dict[str, str] = {}
    runnable = False
    for index, block in enumerate(_runnable_blocks(page), start=1):"""

GO_NEW = '''    files: dict[str, str] = {}
    runnable = False

    # 先铺这一部分的公共底稿。讲义因此不必每章开头重贴一遍前面章节的成果，
    # 而是在 <本页所在目录>/_prelude/ 放几个 .go 文件。
    #
    # 同名以页面里的格子为准（下面的循环后写覆盖先写），这样学生想改掉某个
    # 铺底文件时，写一个同名的格子就行。
    for name, body in _prelude_files(page).items():
        files[name] = body

    for index, block in enumerate(_runnable_blocks(page), start=1):'''

PRELUDE_FN = '''def _prelude_files(page) -> dict[str, str]:
    """读这一页所在目录下 ``_prelude/`` 里的 .go 文件，作为累积编译的底稿。

    没有这个目录就返回空字典——旧讲义（自带完整「本章起点」那种）照跑不误。
    """
    from pathlib import Path as _Path

    cwd = ""
    for block in _runnable_blocks(page):
        cwd = str(((block.payload or {}).get("notebook") or {}).get("cwd") or "")
        if cwd:
            break
    if not cwd:
        return {}

    prelude_dir = _Path(cwd) / "_prelude"
    if not prelude_dir.is_dir():
        return {}

    out: dict[str, str] = {}
    for path in sorted(prelude_dir.glob("*.go")):
        try:
            out[path.name] = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("读不了底稿文件 %s，跳过", path)
    return out


def _go_snippet('''


def main() -> int:
    session = SESSION.read_text(encoding="utf-8")
    if CHDIR_NEW not in session:
        if CHDIR_OLD not in session:
            print("session.py 里没找到 _chdir 的开头，请人工确认。")
            return 1
        session = session.replace(CHDIR_OLD, CHDIR_NEW, 1)
        SESSION.write_text(session, encoding="utf-8")

    api = API.read_text(encoding="utf-8")
    if "_prelude_files" not in api:
        if "def _go_snippet(" not in api:
            print("api.py 里没找到 _go_snippet，请人工确认。")
            return 1
        api = api.replace("def _go_snippet(", PRELUDE_FN, 1)
    if GO_NEW not in api:
        if GO_OLD not in api:
            print("api.py 里没找到累积编译的文件收集循环，请人工确认。")
            return 1
        api = api.replace(GO_OLD, GO_NEW, 1)
    API.write_text(api, encoding="utf-8")

    print("两条通道已打通：Python 走 sys.path 找 agentlib，Go 走 _prelude 铺底稿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
