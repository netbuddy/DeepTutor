"""把内核吐出来的原始消息整理成一份能给人看、也能给模型读的结果。

Jupyter 内核的输出分四类：标准输出流、表达式的值、富显示数据（图片、HTML 表格）、
以及报错回溯。这里的工作是把它们规范化：

* 图片写成文件落在工作目录里，返回一个 ``/api/outputs`` 下的地址，让前端直接显示，
  同时避免把几万个字符的 base64 塞进模型的上下文；
* pandas 表格会同时给出 HTML 和纯文本两种形式，两种都留下——前端用 HTML 显示，
  模型读纯文本；
* 报错回溯里带着终端配色的转义字符，读起来是乱码，要先洗掉。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import re
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote

# 终端配色的转义序列，例如 ESC[0;31m。回溯信息里到处都是。
_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

_IMAGE_SUFFIX = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/svg+xml": ".svg",
    "image/gif": ".gif",
}


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@dataclass
class CellOutput:
    """一个单元格执行完之后的全部产物。"""

    stdout: str = ""
    stderr: str = ""
    text_result: str = ""  # 表达式的值或富显示数据的纯文本形式
    html: str = ""  # 富显示数据的 HTML 形式，pandas 表格走这里
    images: list[dict[str, Any]] = field(default_factory=list)  # {url, path, mime, bytes}
    error: dict[str, str] | None = None  # {ename, evalue, traceback}
    status: str = "ok"  # ok | error | timeout
    elapsed_s: float = 0.0
    execution_count: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "text_result": self.text_result,
            "html": self.html,
            "images": self.images,
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 3),
            "execution_count": self.execution_count,
        }

    def for_model(self, max_chars: int) -> str:
        """给模型读的紧凑文本。图片只报告存在与文件名，不塞 base64。"""
        parts: list[str] = []
        if self.stdout.strip():
            parts.append("标准输出：\n" + self.stdout.strip())
        if self.text_result.strip():
            parts.append("结果值：\n" + self.text_result.strip())
        if self.stderr.strip():
            parts.append("标准错误：\n" + self.stderr.strip())
        if self.images:
            names = "、".join(Path(img["path"]).name for img in self.images)
            parts.append(f"生成了 {len(self.images)} 张图（已显示给学生）：{names}")
        if self.error:
            parts.append(
                f"报错 {self.error['ename']}: {self.error['evalue']}\n"
                + self.error.get("traceback", "")
            )
        if self.status == "timeout":
            parts.append("（执行超时，内核已中断这一格）")
        text = "\n\n".join(parts) or "（没有输出）"
        if len(text) > max_chars:
            half = max_chars // 2
            text = (
                text[:half]
                + f"\n\n…（省略 {len(text) - max_chars:,} 个字符）…\n\n"
                + text[-half:]
            )
        return text


class OutputCollector:
    """边收内核消息边整理。一个单元格一份。"""

    def __init__(self, artifact_dir: Path, url_prefix: str) -> None:
        self.artifact_dir = artifact_dir
        self.url_prefix = url_prefix.rstrip("/")
        self.out = CellOutput()
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._started = time.monotonic()

    def feed(self, msg_type: str, content: dict[str, Any]) -> None:
        if msg_type == "stream":
            target = self._stderr if content.get("name") == "stderr" else self._stdout
            target.append(str(content.get("text", "")))
        elif msg_type in ("execute_result", "display_data", "update_display_data"):
            self._absorb_data(content.get("data") or {})
            if msg_type == "execute_result" and content.get("execution_count") is not None:
                self.out.execution_count = int(content["execution_count"])
        elif msg_type == "error":
            self.out.status = "error"
            self.out.error = {
                "ename": str(content.get("ename", "")),
                "evalue": str(content.get("evalue", "")),
                "traceback": strip_ansi("\n".join(content.get("traceback") or [])),
            }
        elif msg_type == "execute_input" and content.get("execution_count") is not None:
            self.out.execution_count = int(content["execution_count"])

    def _absorb_data(self, data: dict[str, Any]) -> None:
        for mime, payload in data.items():
            if mime in _IMAGE_SUFFIX:
                self._save_image(mime, payload)
            elif mime == "text/html" and not self.out.html:
                self.out.html = payload if isinstance(payload, str) else "".join(payload)
        # 纯文本形式留到最后取，这样表格既有 HTML 也有纯文本。
        plain = data.get("text/plain")
        if plain:
            self.out.text_result = plain if isinstance(plain, str) else "".join(plain)

    def _save_image(self, mime: str, payload: Any) -> None:
        raw = payload if isinstance(payload, str) else "".join(payload)
        suffix = _IMAGE_SUFFIX[mime]
        if mime == "image/svg+xml":
            blob = raw.encode("utf-8")
        else:
            try:
                blob = base64.b64decode(raw)
            except Exception:
                return
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        name = f"figure-{len(self.out.images) + 1}-{int(time.time() * 1000)}{suffix}"
        path = self.artifact_dir / name
        path.write_bytes(blob)
        self.out.images.append(
            {
                "url": f"{self.url_prefix}/{quote(name)}",
                "path": str(path),
                "mime": mime,
                "bytes": len(blob),
            }
        )

    def finish(self, status: str | None = None) -> CellOutput:
        if status:
            self.out.status = status
        self.out.stdout = "".join(self._stdout)
        self.out.stderr = strip_ansi("".join(self._stderr))
        self.out.elapsed_s = time.monotonic() - self._started
        return self.out


__all__ = ["CellOutput", "OutputCollector", "strip_ansi"]
