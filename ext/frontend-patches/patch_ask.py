#!/usr/bin/env python3
"""把单元格上的「问助教」接到书页里那个对话面板上。在 ~/DeepTutor-src 下执行。

单元格组件点按钮时派发一个自定义事件，带着这一格的代码、输出和报错。这里让页面
监听它：打开对话面板，并把一段写好的问题预填进输入框，学生按回车就发出去。

用事件而不是把回调一层层传下去，是为了让改动集中：书页组件树有三层，逐层加 props
会让三个文件都变，升级变基时冲突面更大。
"""

from pathlib import Path

BOOK = Path("web/app/(workspace)/book")

PANEL_PROP = """  initialSessionId?: string | null;
  onSessionResolved?: (sessionId: string) => void;
}"""

PANEL_PROP_NEW = """  initialSessionId?: string | null;
  onSessionResolved?: (sessionId: string) => void;
  /** 从某个可运行单元格带过来的问题，打开面板时预填进输入框。 */
  prefill?: string;
}"""

PANEL_ARGS = """  initialSessionId = null,
  onSessionResolved,
}: BookChatPanelProps) {"""

PANEL_ARGS_NEW = """  initialSessionId = null,
  onSessionResolved,
  prefill,
}: BookChatPanelProps) {"""

PANEL_STATE = '  const [input, setInput] = useState("");'
PANEL_STATE_NEW = '''  const [input, setInput] = useState("");

  // 学生在某一格点了「问助教」：把带上下文的问题填进输入框，光标停在末尾，
  // 让他可以先补一句自己的疑问再发出去。
  useEffect(() => {
    if (prefill) setInput(prefill);
  }, [prefill]);'''

PAGE_STATE = "  const [chatOpen, setChatOpen] = useState(false);"
PAGE_STATE_NEW = '''  const [chatOpen, setChatOpen] = useState(false);
  const [cellQuestion, setCellQuestion] = useState("");

  // 可运行单元格上的「问助教」按钮派发这个事件，带着那一格的代码与运行结果。
  useEffect(() => {
    function onAskAboutCell(event: Event) {
      const detail = (event as CustomEvent).detail || {};
      const lines = [
        `我在看${detail.cellIndex ? `第 ${detail.cellIndex} 格` : "这一格"}代码：`,
        "```python",
        String(detail.code || "").slice(0, 2000),
        "```",
      ];
      if (detail.error) {
        lines.push(`它报错了：${detail.error}`, "这是什么原因，该怎么改？");
      } else if (detail.stdout || detail.textResult) {
        lines.push(
          `运行结果是：${String(detail.stdout || detail.textResult).slice(0, 800)}`,
          "请解释这段代码做了什么，结果说明了什么。",
        );
      } else {
        lines.push("请解释这段代码做了什么。");
      }
      setCellQuestion(lines.join("\\n"));
      setChatOpen(true);
    }
    window.addEventListener("ext:ask-about-cell", onAskAboutCell);
    return () => window.removeEventListener("ext:ask-about-cell", onAskAboutCell);
  }, []);'''

PAGE_PANEL = """            onSessionResolved={(sessionId) =>
              void handlePageChatSession(sessionId)
            }
          />"""
PAGE_PANEL_NEW = """            onSessionResolved={(sessionId) =>
              void handlePageChatSession(sessionId)
            }
            prefill={cellQuestion}
          />"""


def patch(path: Path, pairs: list[tuple[str, str]]) -> bool:
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in text:
            continue
        if old not in text:
            print(f"在 {path} 里没找到要替换的片段，请人工确认：\n{old[:70]}…")
            return False
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return True


def ensure_use_effect(path: Path) -> None:
    """确保文件从 react 里导入了 useEffect。"""
    text = path.read_text(encoding="utf-8")
    if "useEffect" not in text.split("\n\n")[0] and "useEffect," not in text:
        text = text.replace('import { useState', 'import { useEffect, useState', 1)
        path.write_text(text, encoding="utf-8")


def main() -> int:
    panel = BOOK / "components/BookChatPanel.tsx"
    page = BOOK / "page.tsx"

    ok = patch(
        panel,
        [(PANEL_PROP, PANEL_PROP_NEW), (PANEL_ARGS, PANEL_ARGS_NEW), (PANEL_STATE, PANEL_STATE_NEW)],
    )
    ok = patch(page, [(PAGE_STATE, PAGE_STATE_NEW), (PAGE_PANEL, PAGE_PANEL_NEW)]) and ok
    if not ok:
        return 1
    print("对话面板与书页已接上「问助教」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
