"""第 2 章：消息与内容块。

一条消息不是一个字符串，是一串「块」。这样一条助手消息才能同时装下
「它说的话」和「它要调的工具」——这两样在同一条消息里是常态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Iterator, Literal, Protocol
import uuid


def new_id(prefix: str) -> str:
    """给消息、工具调用之类的东西发一个短标识。带前缀是为了在日志里一眼认出类型。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class TextBlock:
    """一段文字。"""

    text: str
    type: Literal["text"] = "text"


@dataclass
class ToolUseBlock:
    """模型要求调一个工具。id 是这次调用的凭据，结果必须带着它回来。"""

    name: str
    args: dict[str, Any]
    id: str = field(default_factory=lambda: new_id("call"))
    type: Literal["tool_use"] = "tool_use"


@dataclass
class ToolResultBlock:
    """一次工具调用的结果。tool_use_id 指回是哪一次调用。"""

    tool_use_id: str
    content: str
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"


@dataclass
class Message:
    """一条消息：谁说的，以及内容块的列表。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: list[Any]
    id: str = field(default_factory=lambda: new_id("msg"))
    created_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def tool_results(self) -> list[ToolResultBlock]:
        return [b for b in self.content if isinstance(b, ToolResultBlock)]


@dataclass
class Delta:
    """流式输出里的一小片。要么是几个字，要么是一次拼好的工具调用。"""

    kind: Literal["text", "tool_use"]
    text: str = ""
    tool: ToolUseBlock | None = None


class Model(Protocol):
    """第 5 章定下的模型接口。假模型和真模型的唯一区别是这个方法怎么实现。"""

    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[Delta]: ...


__all__ = [
    "Delta",
    "Message",
    "Model",
    "TextBlock",
    "ToolResultBlock",
    "ToolUseBlock",
    "new_id",
]
