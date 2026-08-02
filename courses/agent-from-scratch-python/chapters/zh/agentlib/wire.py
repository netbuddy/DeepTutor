"""第 6、7 章：供应商适配与流式解析。

我们自己的消息结构（第 2 章）和 OpenAI 兼容接口的线上格式不一样，这里做双向翻译。
把这层单独放着的理由是：换一家模型服务，只有这个文件要改。
"""

from __future__ import annotations

import json
from typing import Any

from agentlib.blocks import Message, TextBlock, ToolResultBlock, ToolUseBlock, new_id


def to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """我们的消息 → 线上格式。

    两处不对称要注意：工具结果在我们这里是一条 tool 消息里的若干块，
    在线上格式里是若干条 role=tool 的消息；助手带工具调用时，
    content 允许为 null，但 tool_calls 必须在。
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            for b in m.content:
                if isinstance(b, ToolResultBlock):
                    out.append(
                        {"role": "tool", "tool_call_id": b.tool_use_id, "content": b.content}
                    )
            continue
        text, calls = m.text(), m.tool_uses()
        if m.role == "assistant" and calls:
            out.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(c.args, ensure_ascii=False),
                            },
                        }
                        for c in calls
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": text})
    return out


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """工具声明 → 线上格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


class ToolCallAccumulator:
    """把流式吐出来的工具调用碎片拼回完整的调用。

    服务端是一个字符一个字符地吐参数的，而且用 index 标明这是第几个调用。
    不按 index 归位而按到达顺序拼，两个并发的调用会被拼成一团乱码。
    """

    def __init__(self) -> None:
        self._slots: dict[int, dict[str, str]] = {}

    def feed(self, raw_calls: list[dict[str, Any]]) -> None:
        for item in raw_calls:
            slot = self._slots.setdefault(
                int(item.get("index", 0)), {"id": "", "name": "", "arguments": ""}
            )
            if item.get("id"):
                slot["id"] = item["id"]
            fn = item.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]

    def finish(self) -> list[ToolUseBlock]:
        out: list[ToolUseBlock] = []
        for i in sorted(self._slots):
            slot = self._slots[i]
            raw = slot["arguments"] or "{}"
            try:
                args = json.loads(raw)
                if not isinstance(args, dict):
                    args = {"_raw": raw}
            except json.JSONDecodeError:
                # 模型偶尔会吐出半截 JSON。这不是我们的 bug，也不该让程序崩，
                # 而是要作为「参数不合格」交给第 9 章的校验去处理。
                args = {"_invalid_json": raw}
            out.append(
                ToolUseBlock(id=slot["id"] or new_id("call"), name=slot["name"], args=args)
            )
        return out


def parse_sse_line(line: str) -> dict[str, Any] | None:
    """解析一行 SSE。不是数据行、是心跳、是结束标记，都返回 None。"""
    line = line.strip()
    if not line or line.startswith(":") or not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


__all__ = [
    "ToolCallAccumulator",
    "parse_sse_line",
    "to_openai_messages",
    "to_openai_tools",
]
