"""前面各章逐格写出来的东西，一行没改，只是收进了一个包。

每章开头写一行 ``from agentlib import *`` 就能拿到它们，不必再把两百行代码
重贴一遍。想看某一段当初是怎么来的，直接打开对应的文件：

| 文件 | 对应章节 | 装了什么 |
|---|---|---|
| ``blocks.py`` | 第 2 章 | 消息、内容块、Delta、Model 接口 |
| ``events.py`` | 第 3 章 | 事件流 |
| ``wire.py`` | 第 6、7 章 | 线上格式的双向翻译、流式解析 |
| ``model.py`` | 第 5、8 章 | 脚本化的假模型、OpenAI 兼容的真模型 |
| ``tools.py`` | 第 9 章 | 工具契约、参数校验、登记处 |

这个包住在课程目录里，随课程包一起分发。内核启动时会把课程目录加进
``sys.path``，所以 import 得到。
"""

from agentlib.blocks import (
    Delta,
    Message,
    Model,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    new_id,
)
from agentlib.events import Event, EventStream
from agentlib.model import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OpenAICompatModel,
    ScriptedModel,
    ScriptedTurn,
    default_model,
)
from agentlib.tools import (
    CALC_TOOL,
    TIME_TOOL,
    Tool,
    ToolRegistry,
    ToolResult,
    calculate,
    default_registry,
    get_time,
    validate_args,
)
from agentlib.wire import (
    ToolCallAccumulator,
    parse_sse_line,
    to_openai_messages,
    to_openai_tools,
)

__all__ = [
    "CALC_TOOL",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "Delta",
    "Event",
    "EventStream",
    "Message",
    "Model",
    "OpenAICompatModel",
    "ScriptedModel",
    "ScriptedTurn",
    "TIME_TOOL",
    "TextBlock",
    "Tool",
    "ToolCallAccumulator",
    "ToolRegistry",
    "ToolResult",
    "ToolResultBlock",
    "ToolUseBlock",
    "calculate",
    "default_model",
    "default_registry",
    "get_time",
    "new_id",
    "parse_sse_line",
    "to_openai_messages",
    "to_openai_tools",
    "validate_args",
]
