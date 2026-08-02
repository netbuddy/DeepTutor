"""内核容器的连接参数与运行限额。

学生的代码跑在一个独立容器里的 Jupyter 服务上，宿主与它之间只有一条 HTTP 通道。
这里集中放连接地址、访问口令的读取方式，以及几条运行限额。

访问口令存在文件里而不是写进代码或环境变量：容器启动脚本生成它，服务端读它，
两边都不打印。文件权限设为仅本人可读。
"""

from __future__ import annotations

import os
from pathlib import Path

# 容器里的 Jupyter 服务地址。只绑本机回环，局域网访问不到。
BASE_URL = os.environ.get("DEEPTUTOR_EXT_KERNEL_URL", "http://127.0.0.1:9189").rstrip("/")

# 访问口令的存放位置。由 bin/kernel-container.sh 生成。
TOKEN_FILE = Path(
    os.environ.get("DEEPTUTOR_EXT_KERNEL_TOKEN_FILE", "~/DeepTutor-ext/.kernel-token")
).expanduser()

# 同时存活的内核数上限。每个内核大约占 150 到 300 MB，加载数据集后可能到 1 GB 以上。
# 容器内存 6 GB，12 个是留了余量的上限。
#
# 这个数字不能太小：一门课有二十来页，学生翻页时每页一个内核，上限太低会导致
# 频繁地回收再新建，而新建内核要十几秒——表现是「翻回上一页点运行要等半天」。
MAX_LIVE_KERNELS = int(os.environ.get("DEEPTUTOR_EXT_MAX_KERNELS", "12"))

# 内核闲置多久后自动回收（秒）。学生看讲解、写作业的间隙不该被打断，所以给得比较宽。
IDLE_TIMEOUT_S = int(os.environ.get("DEEPTUTOR_EXT_KERNEL_IDLE_S", "1800"))

# 单个单元格的执行时限（秒）。训练模型的格子可能要跑一会儿，但不能无限等。
DEFAULT_EXEC_TIMEOUT_S = int(os.environ.get("DEEPTUTOR_EXT_EXEC_TIMEOUT_S", "120"))
MAX_EXEC_TIMEOUT_S = 600

# 单次执行回传给模型的文本上限。图片不受这个限制，它落成文件。
MAX_TEXT_CHARS = 4000


def read_token() -> str:
    """读取访问口令。容器没起来或口令文件缺失时返回空字符串，由调用方给出可读的报错。"""
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


__all__ = [
    "BASE_URL",
    "DEFAULT_EXEC_TIMEOUT_S",
    "IDLE_TIMEOUT_S",
    "MAX_EXEC_TIMEOUT_S",
    "MAX_LIVE_KERNELS",
    "MAX_TEXT_CHARS",
    "TOKEN_FILE",
    "read_token",
]
