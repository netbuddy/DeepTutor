"""第 5 章的假模型与第 8 章的真模型。

两个都实现同一个 Model 接口，所以调用它们的代码一个字都不用改——
这是第 5 章「先定接口再写实现」的全部回报。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterator
import urllib.request

from agentlib.blocks import Delta, Message, ToolUseBlock
from agentlib.wire import (
    ToolCallAccumulator,
    parse_sse_line,
    to_openai_messages,
    to_openai_tools,
)


@dataclass
class ScriptedTurn:
    """剧本里的一幕：模型这一轮说什么、要调哪些工具。"""

    text: str = ""
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


class ScriptedModel:
    """第 5 章的假模型：按剧本出牌，不联网，结果完全确定。

    它的价值不在于省钱，在于**让主循环可以被确定性地测试**。
    真模型每次说的话都不一样，用它调不出主循环的 bug。
    """

    def __init__(self, script: list[ScriptedTurn], chunk_size: int = 4,
                 repeat_last: bool = False) -> None:
        self.script = script
        self.chunk_size = chunk_size
        self.repeat_last = repeat_last
        self.calls = 0

    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[Delta]:
        index = self.calls
        self.calls += 1
        if self.repeat_last and index >= len(self.script):
            index = len(self.script) - 1
        if index >= len(self.script):
            raise RuntimeError(
                f"剧本只有 {len(self.script)} 幕，模型却被调用了第 {index + 1} 次。"
                f"多半是主循环没有正常结束——去看看退出条件。"
            )
        turn = self.script[index]
        for i in range(0, len(turn.text), self.chunk_size):
            yield Delta(kind="text", text=turn.text[i : i + self.chunk_size])
        for name, args in turn.calls:
            yield Delta(kind="tool_use", tool=ToolUseBlock(name=name, args=args))


class OpenAICompatModel:
    """第 8 章的真模型：接任何 OpenAI 兼容的服务。"""

    def __init__(self, base_url: str, model: str, timeout: int = 180,
                 temperature: float | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    def stream(self, messages: list[Message], tools: list[dict] | None = None) -> Iterator[Delta]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "stream": True,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if tools:
            body["tools"] = to_openai_tools(tools)

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        acc = ToolCallAccumulator()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            for raw in resp:
                chunk = parse_sse_line(raw.decode("utf-8", errors="replace"))
                if chunk is None:
                    continue
                delta = ((chunk.get("choices") or [{}])[0]).get("delta") or {}
                if delta.get("content"):
                    yield Delta(kind="text", text=delta["content"])
                if delta.get("tool_calls"):
                    acc.feed(delta["tool_calls"])
        # 工具调用要等整条流读完才拼得齐，所以放在最后一次性吐出来。
        for block in acc.finish():
            yield Delta(kind="tool_use", tool=block)


# 课程里用的本地模型。换成你自己的地址即可，接口是 OpenAI 兼容的。
DEFAULT_BASE_URL = "http://192.168.213.116:8084/v1"
DEFAULT_MODEL = "qwen3.6-27B"


def default_model(temperature: float | None = None) -> OpenAICompatModel:
    return OpenAICompatModel(DEFAULT_BASE_URL, DEFAULT_MODEL, temperature=temperature)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "OpenAICompatModel",
    "ScriptedModel",
    "ScriptedTurn",
    "default_model",
]
