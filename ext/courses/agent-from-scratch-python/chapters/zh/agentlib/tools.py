"""第 9 章：工具契约。

一个工具要声明三件事：名字与用途（给模型看）、参数结构（给模型和校验器看）、
执行体（给我们看）。这里还带着那条核心约定：**执行工具永远不抛异常**，
所有出错的方式都翻译成结果回给模型。
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import json
from typing import Any, Callable


@dataclass
class ToolResult:
    """一次工具执行的结果。

    三个字段而不是「成功 or 失败」两种：参数不合格是第三种，
    它值得让模型重填一次，而执行失败通常不值得。
    """

    content: str
    is_error: bool = False
    is_invalid_args: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str]
    # 能不能和别的工具同时跑。只读工具是多数，所以默认能。
    concurrency_safe: bool = True

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def validate_args(args: Any, schema: dict[str, Any]) -> str:
    """校验参数。合格返回空字符串，不合格返回**给模型看的**一句人话。

    只做工具参数用得到的那一小部分 JSON Schema：对象、必填、基础类型、枚举。
    为这四样引入一个第三方库不划算。
    """
    if not isinstance(args, dict):
        return "参数必须是一个对象"
    if "_invalid_json" in args:
        return f"参数不是合法的 JSON：{str(args['_invalid_json'])[:120]}"

    props = schema.get("properties") or {}
    required = schema.get("required") or []

    missing = [k for k in required if k not in args]
    if missing:
        return f"缺少必填参数 {'、'.join(missing)}"
    unknown = [k for k in args if k not in props]
    if unknown:
        return f"不认识的参数 {'、'.join(unknown)}；这个工具接受 {'、'.join(props)}"

    checks = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for key, value in args.items():
        spec = props[key]
        expected = checks.get(spec.get("type"))
        if expected and not isinstance(value, expected):
            return f"参数 {key} 应该是 {spec.get('type')}，收到的是 {type(value).__name__}"
        if spec.get("enum") and value not in spec["enum"]:
            return f"参数 {key} 只能是 {'、'.join(map(str, spec['enum']))} 之一"
    return ""


class ToolRegistry:
    """工具登记处。所有出错的地方都在这里被拦住。"""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in (tools or [])}

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self, exclude: tuple[str, ...] | set[str] = ()) -> list[dict[str, Any]]:
        return [t.spec() for n, t in self._tools.items() if n not in exclude]

    def execute(self, name: str, args: dict[str, Any], **extra: Any) -> ToolResult:
        """执行一个工具调用。

        这个方法的核心约定：**它永远不抛异常。** 所有出错的方式都被翻译成
        ToolResult 回给模型。主循环因此不需要为工具写任何错误处理。
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                f"没有叫 {name} 的工具。可用的：{'、'.join(self.names())}", is_error=True
            )
        problem = validate_args(args, tool.parameters)
        if problem:
            return ToolResult(f"参数不合格：{problem}", is_error=True, is_invalid_args=True)
        try:
            return ToolResult(str(tool.run(**args, **extra)))
        except Exception as exc:  # noqa: BLE001 — 工具是别人写的代码，什么都可能抛
            return ToolResult(f"{type(exc).__name__}: {exc}", is_error=True)


# ── 课程里反复用到的两个小工具 ────────────────────────────────────────


def get_time(city: str, unit: str = "24h") -> str:
    now = datetime.datetime.now()
    return f"{city} 现在是 {now.strftime('%H:%M') if unit == '24h' else now.strftime('%I:%M %p')}"


def calculate(expression: str) -> str:
    """算一个算术表达式。

    没有直接 eval：工具的输入始终不可信——它来自模型，而模型的输入来自用户。
    这里先用字符白名单挡掉一切非算术字符，再在一个没有内置函数的环境里求值。
    """
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        raise ValueError(f"表达式里有不允许的字符：{sorted(set(expression) - allowed)}")
    return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307 — 见上方说明


TIME_TOOL = Tool(
    "get_time",
    "查询某个城市的当前时间",
    {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名"},
            "unit": {"type": "string", "enum": ["24h", "12h"]},
        },
        "required": ["city"],
    },
    get_time,
)

CALC_TOOL = Tool(
    "calculate",
    "计算一个算术表达式，比如 (3+5)*2",
    {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "只含数字和 + - * / ( )"}
        },
        "required": ["expression"],
    },
    calculate,
)


def default_registry() -> ToolRegistry:
    return ToolRegistry([TIME_TOOL, CALC_TOOL])


__all__ = [
    "CALC_TOOL",
    "TIME_TOOL",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "calculate",
    "default_registry",
    "get_time",
    "validate_args",
]
