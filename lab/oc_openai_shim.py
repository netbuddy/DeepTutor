#!/usr/bin/env python3
"""把 opencode 的本地服务包成一个 OpenAI 兼容端点（可行性验证用的最小实现）。

opencode 自己没有 `/v1/chat/completions`——它的服务只提供会话式接口，一次提问对应
一次「建会话 → 发消息 → 等它把活干完」。这个转接层做的就是两种语义之间的翻译：

  OpenAI 的调用是无状态的（每次带上完整对话），opencode 的会话是有状态的。
  所以这里每次请求都新建一个 opencode 会话，把历史消息拼成一段提示发进去，
  拿到回答就结束。语义上最接近，代价是丢掉 opencode 自己的上下文复用。

流式也能对上：opencode 的事件总线会推逐字增量，把它转写成 OpenAI 的 chunk 即可。

这是可行性验证，不是产品实现——第 4 节列的那些取舍（工具调用、会话复用、用量统计）
都没有处理。跑法：

    <虚拟环境的 python> oc_openai_shim.py            # 监听 127.0.0.1:4097
"""

from __future__ import annotations

import json
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

OPENCODE = "http://127.0.0.1:4096"
# opencode 干活可能很久（它会自己调工具、改文件），读取不设超时，等它自己结束。
TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=60.0, pool=10.0)

app = FastAPI(title="opencode 的 OpenAI 兼容转接层")


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = ""


class ChatRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


def _text_of(content) -> str:
    """OpenAI 的 content 可以是字符串，也可以是分段数组，两种都收。"""
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return str(content or "")


def _flatten(messages: list[ChatMessage]) -> tuple[str, str]:
    """把消息数组压成（系统提示，提示正文）。

    opencode 的会话里只有「系统提示」和「用户消息」两个位置，没有 OpenAI 那种
    多轮 role 数组，所以历史轮次要拼进正文，并标明谁说的，模型才能读懂上下文。
    """
    system_parts: list[str] = []
    turns: list[str] = []
    for message in messages:
        text = _text_of(message.content).strip()
        if not text:
            continue
        if message.role == "system":
            system_parts.append(text)
        elif message.role == "assistant":
            turns.append(f"（上一轮你的回答）{text}")
        else:
            turns.append(text)
    return "\n\n".join(system_parts), "\n\n".join(turns)


def _model_ref(model: str) -> dict | None:
    """把 OpenAI 的 model 字段拆成 opencode 要的 {providerID, modelID}。"""
    raw = (model or "").strip()
    if not raw or "/" not in raw:
        return None
    provider, _, model_id = raw.partition("/")
    return {"providerID": provider, "modelID": model_id}


async def _new_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/session", json={"title": "openai-compat"})
    response.raise_for_status()
    payload = response.json()
    session_id = str((payload.get("data") or payload).get("id") or "")
    if not session_id:
        raise HTTPException(status_code=502, detail="opencode 没有返回会话标识")
    return session_id


def _message_body(system: str, prompt: str, model: str) -> dict:
    body: dict = {"parts": [{"type": "text", "text": prompt}]}
    reference = _model_ref(model)
    if reference:
        body["model"] = reference
    if system:
        body["system"] = system
    return body


def _collect_answer(payload: dict) -> str:
    """从 opencode 的回复里取出最终文本。"""
    data = payload.get("data") or payload
    parts = data.get("parts") or []
    chunks = [
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    return "\n".join(chunk for chunk in chunks if chunk.strip()).strip()


@app.get("/v1/models")
async def list_models() -> dict:
    async with httpx.AsyncClient(base_url=OPENCODE, timeout=30.0) as client:
        response = await client.get("/api/model")
        response.raise_for_status()
        entries = response.json().get("data") or []
    return {
        "object": "list",
        "data": [
            {
                "id": f"{entry.get('providerID')}/{entry.get('id')}",
                "object": "model",
                "created": 0,
                "owned_by": str(entry.get("providerID") or "opencode"),
            }
            for entry in entries
            if entry.get("id")
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(body: ChatRequest):
    system, prompt = _flatten(body.messages)
    if not prompt:
        raise HTTPException(status_code=400, detail="messages 里没有可发送的内容")

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if not body.stream:
        async with httpx.AsyncClient(base_url=OPENCODE, timeout=TIMEOUT) as client:
            session_id = await _new_session(client)
            response = await client.post(
                f"/session/{session_id}/message", json=_message_body(system, prompt, body.model)
            )
            response.raise_for_status()
            answer = _collect_answer(response.json())
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": body.model or "opencode",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            # opencode 不回报 token 用量，这里给零而不是编造数字。
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def stream():
        chunk_head = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model or "opencode",
        }
        yield "data: " + json.dumps(
            {**chunk_head, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
        ) + "\n\n"

        async with httpx.AsyncClient(base_url=OPENCODE, timeout=TIMEOUT) as client:
            session_id = await _new_session(client)
            seen: dict[str, str] = {}
            # 先挂上事件流再发消息，否则开头几个增量会漏掉。
            async with client.stream("GET", "/event") as events:
                post = client.post(
                    f"/session/{session_id}/message",
                    json=_message_body(system, prompt, body.model),
                )
                import asyncio

                task = asyncio.create_task(post)
                async for line in events.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    props = event.get("properties") or {}
                    if str(props.get("sessionID") or "") not in ("", session_id):
                        continue
                    if event.get("type") == "message.part.delta":
                        part_id = str(props.get("partID") or "")
                        delta = str(props.get("delta") or "")
                        if delta:
                            seen[part_id] = seen.get(part_id, "") + delta
                            yield "data: " + json.dumps(
                                {
                                    **chunk_head,
                                    "choices": [
                                        {"index": 0, "delta": {"content": delta}, "finish_reason": None}
                                    ],
                                }
                            ) + "\n\n"
                    if task.done():
                        break
                if not task.done():
                    await task

        yield "data: " + json.dumps(
            {**chunk_head, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        ) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=4097, log_level="warning")
