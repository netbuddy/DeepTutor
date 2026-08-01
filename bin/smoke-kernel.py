#!/usr/bin/env python3
"""内核会话服务的冒烟测试：跨格状态、图片落盘与公开地址、表格、报错、重置。

跑法：<DeepTutor 虚拟环境的 python> bin/smoke-kernel.py
前提：内核容器已启动（make kernel-start），课程目录里有 ML-For-Beginners 的回归模块。

图片那一项特意验证到「地址真的能取回文件」这一步——产物落在哪个目录不是随便选的，
DeepTutor 对哪些路径可以经 /api/outputs 公开有一份白名单，落错地方就是 404，
而这种错误在界面上表现为图裂，很难一眼归因。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 数据根跟着这个环境变量走。不设的话它会按当前工作目录去猜，产物就落到
# ~/DeepTutor-ext/data 里去了，而服务读的是 ~/DeepTutor-src/data，图片取不回来。
os.environ.setdefault("DEEPTUTOR_HOME", str(Path.home() / "DeepTutor-src"))

SESSION = "smoke-test"
COURSE_DIR = str(Path.home() / "DeepTutor-src/data/user/courses/ml-for-beginners/2-Regression/3-Linear/solution")

results: list[tuple[bool, str, str]] = []


def check(ok: bool, title: str, detail: str = "") -> None:
    results.append((ok, title, detail))
    print(f"{'✓' if ok else '✗'} {title}" + (f"  —  {detail}" if detail else ""))


async def main() -> int:
    from deeptutor_ext.kernel import client, get_session_manager

    if not await client.ping():
        print("内核容器没有应答。先执行：cd ~/DeepTutor-ext && make kernel-start", file=sys.stderr)
        return 1

    manager = get_session_manager()
    await manager.reset(SESSION)

    out = await manager.execute(SESSION, "a = 6 * 7", cwd=COURSE_DIR)
    check(out.ok, "能在容器里执行代码", f"耗时 {out.elapsed_s:.2f}s")

    out = await manager.execute(SESSION, "a")
    check(out.text_result.strip() == "42", "跨调用保持变量", f"取回 {out.text_result.strip()!r}")

    out = await manager.execute(SESSION, "import os; os.getcwd()")
    check(COURSE_DIR in out.text_result, "工作目录切到了课程所在位置", out.text_result.strip())

    out = await manager.execute(
        SESSION,
        "import pandas as pd\n"
        "pumpkins = pd.read_csv('../../data/US-pumpkins.csv')\n"
        "pumpkins[['City Name','Package','Low Price','High Price']].head(3)",
    )
    check(
        out.ok and bool(out.html) and "<table" in out.html,
        "课程数据能按相对路径读到，表格有 HTML 形式",
        f"HTML {len(out.html)} 字符",
    )

    out = await manager.execute(
        SESSION,
        "import matplotlib.pyplot as plt\nplt.plot([1,4,9]); plt.title('smoke'); plt.show()",
    )
    check(bool(out.images), "画图产生了图片文件", f"{len(out.images)} 张")

    if out.images:
        image = out.images[0]
        check(Path(image["path"]).is_file(), "图片确实落在磁盘上", f"{image['bytes']} 字节")

        from deeptutor.services.path_service import get_path_service

        check(
            get_path_service().is_public_output_path(image["path"]),
            "图片位于可公开访问的白名单路径内",
            image["url"],
        )

        import httpx

        try:
            response = httpx.get(f"http://127.0.0.1:9188{image['url']}", timeout=15)
            fetched = response.status_code == 200 and len(response.content) == image["bytes"]
            detail = f"HTTP {response.status_code}，取回 {len(response.content)} 字节"
        except httpx.HTTPError as exc:
            fetched, detail = False, f"请求失败：{type(exc).__name__}（后端没起的话这项会失败）"
        check(fetched, "前端能通过该地址取回图片", detail)

    out = await manager.execute(SESSION, "1/0")
    check(
        out.status == "error" and out.error and out.error["ename"] == "ZeroDivisionError",
        "报错被完整捕获",
        f"{out.error['ename']}: {out.error['evalue']}" if out.error else "",
    )

    out = await manager.execute(SESSION, "a * 2")
    check(out.text_result.strip() == "84", "报错没有打断内核，变量还在", out.text_result.strip())

    await manager.reset(SESSION)
    out = await manager.execute(SESSION, "'a' in dir()", cwd=COURSE_DIR)
    check(out.text_result.strip() == "False", "重置之后是一个干净的内核", out.text_result.strip())

    await manager.reset(SESSION)

    failed = sum(1 for ok, _, _ in results if not ok)
    print("-" * 60)
    print(f"{len(results)} 项检查，失败 {failed} 项。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
