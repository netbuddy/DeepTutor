"""第 3 章：事件流。

agent 干活时外界要能看到进展。做法不是让主循环直接去打印——那样换个界面就得
改主循环——而是让它往一条事件流上发东西，谁想看谁来订阅。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Event:
    kind: str
    data: dict[str, Any]


class EventStream:
    """一条事件流。发的人不关心有没有人在听，听的人不关心是谁发的。"""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        """登记一个订阅者，返回取消订阅的函数。"""
        self._subscribers.append(fn)

        def unsubscribe() -> None:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

        return unsubscribe

    def emit(self, kind: str, **data: Any) -> None:
        """广播一个事件。

        订阅者抛异常不能连累发事件的人——界面代码出 bug 是常事，
        不该让 agent 跟着一起死。遍历前先拷一份，免得订阅者在回调里增删列表。
        """
        event = Event(kind=kind, data=data)
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception as exc:  # noqa: BLE001 — 故意兜住一切
                print(f"  [订阅者出错，已忽略] {type(exc).__name__}: {exc}")


__all__ = ["Event", "EventStream"]
