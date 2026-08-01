"""自检工具：报告扩展包接进 DeepTutor 的情况。

它存在的理由是升级后的验收：DeepTutor 每次升版都可能改动我们赖以接入的位置，
而接入失败是静默的——工具只是不出现，界面上看不出任何异常。有了这个工具，
升级后跑一次 `make verify` 就能立刻知道扩展有没有挂上、挂上了哪些。
"""

from __future__ import annotations

from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult


class ExtStatusTool(BaseTool):
    """报告扩展包的版本与已接入的工具清单。"""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ext_status",
            description=(
                "Report which DeepTutor extension tools are installed and active. "
                "Use only when the user asks whether the extension is working."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.__version__ import __version__ as host_version

        from deeptutor_ext import __version__ as ext_version
        from deeptutor_ext.integrate import EXTENSION_TOOL_TYPES

        names = [tool_type().name for tool_type in EXTENSION_TOOL_TYPES]
        lines = [
            f"扩展包版本 {ext_version}，宿主 DeepTutor 版本 {host_version}。",
            f"已接入 {len(names)} 个扩展工具：" + "、".join(names) + "。",
        ]
        return ToolResult(
            content="\n".join(lines),
            metadata={
                "ext_version": ext_version,
                "host_version": host_version,
                "ext_tools": names,
            },
        )


__all__ = ["ExtStatusTool"]
