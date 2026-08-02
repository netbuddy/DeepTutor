#!/usr/bin/env python3
"""把「问助教」从「预填一大段文字」改成「引用一格代码」。在 ~/DeepTutor-src 下执行。

第一版的做法是把这一格的代码拼成一段话，整个塞进输入框。实测下来有三个问题：

1. 输入框是 rows={1} 的单行高度（32 像素），却被塞进 425 字符 / 14 行内容，
   学生只能看到最后一行，要往上滚才知道里面是什么。
2. 学生真正要写的那句问题，得挤在自己看不全的一堆代码后面。
3. 面板上没有任何「正在处理」的提示，而这条链路首字实测要 28 秒
   （同样上下文直连模型只要 4.8 秒，其余是问答流水线自己的开销），
   学生会以为没反应。

改法：
- 代码不再进输入框，而是变成输入框上方一张可展开、可移除的引用卡片；
  输入框留空，专门给学生写自己的问题。
- 发给模型时再把引用的代码拼进去，聊天记录里的那条用户消息只显示
  「问题 +（附第 N 格代码）」，不刷屏。
- 输入框随内容自动增高（1 到 8 行）。
- 发出去之后立刻插一条占位气泡说明助教在读这一页，别让人对着空白等。
"""

from pathlib import Path

BOOK = Path("web/app/(workspace)/book")

# ── BookChatPanel.tsx ────────────────────────────────────────────────────

PANEL_PROP_OLD = """  initialSessionId?: string | null;
  onSessionResolved?: (sessionId: string) => void;
  /** 从某个可运行单元格带过来的问题，打开面板时预填进输入框。 */
  prefill?: string;
}"""

PANEL_PROP_NEW = """  initialSessionId?: string | null;
  onSessionResolved?: (sessionId: string) => void;
  /** 从某个可运行单元格带过来的引用。它不进输入框，只作为附带的上下文。 */
  cellRef?: CellReference | null;
  /** 学生按叉号移除引用，或者发送之后清掉。 */
  onClearCellRef?: () => void;
}

/** 「问助教」带过来的一格代码及其运行结果。 */
export type CellReference = {
  /** 给人看的标题，例如「第 3 格代码」。 */
  label: string;
  code: string;
  output?: string;
  error?: string;
};"""

PANEL_ARGS_OLD = """  initialSessionId = null,
  onSessionResolved,
  prefill,
}: BookChatPanelProps) {"""

PANEL_ARGS_NEW = """  initialSessionId = null,
  onSessionResolved,
  cellRef = null,
  onClearCellRef,
}: BookChatPanelProps) {"""

PANEL_STATE_OLD = '''  const [input, setInput] = useState("");

  // 学生在某一格点了「问助教」：把带上下文的问题填进输入框，光标停在末尾，
  // 让他可以先补一句自己的疑问再发出去。
  useEffect(() => {
    if (prefill) setInput(prefill);
  }, [prefill]);'''

PANEL_STATE_NEW = '''  const [input, setInput] = useState("");
  const [cellRefOpen, setCellRefOpen] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // 新引用进来时收起代码预览，并把光标放进输入框——学生接下来要做的事是写问题，
  // 不是读自己刚才看过的代码。
  useEffect(() => {
    if (!cellRef) return;
    setCellRefOpen(false);
    inputRef.current?.focus();
  }, [cellRef]);

  // 输入框随内容增高，上限 8 行。上游写死 rows={1}，一旦内容多于一行就只能看到最后一行。
  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 176)}px`;
  }, [input]);'''

# 发送时把引用拼进去，但聊天记录里只留一个简短标记
PANEL_SEND_OLD = """  async function send() {
    const text = input.trim();
    if ((!text && attachments.length === 0) || busy || !book || !page) return;
    const userContent =
      text ||
      (attachments.some((item) => item.type === "image")
        ? t(
            "Please analyze the attached image(s) using this chapter as context.",
          )
        : t("Please use the attached file(s) and this chapter as context."));
    const sentAttachments = attachments.map(messageAttachment);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: userContent, attachments: sentAttachments },
    ]);
    setInput("");"""

PANEL_SEND_NEW = """  async function send() {
    const text = input.trim();
    if ((!text && attachments.length === 0 && !cellRef) || busy || !book || !page)
      return;
    const userContent =
      text ||
      (cellRef
        ? "请解释这段代码做了什么。"
        : attachments.some((item) => item.type === "image")
          ? t(
              "Please analyze the attached image(s) using this chapter as context.",
            )
          : t("Please use the attached file(s) and this chapter as context."));

    // 发给模型的内容 = 学生的问题 + 引用的那一格；
    // 聊天记录里显示的只是问题加一行「附：第 N 格代码」，免得代码把面板刷满。
    const outgoing = cellRef
      ? [
          userContent,
          "",
          `我说的是${cellRef.label}：`,
          "```",
          cellRef.code.slice(0, 4000),
          "```",
          cellRef.error
            ? `它报错了：${cellRef.error}`
            : cellRef.output
              ? `它的运行结果是：${cellRef.output.slice(0, 1200)}`
              : "",
        ]
          .filter(Boolean)
          .join("\\n")
      : userContent;
    const shownContent = cellRef
      ? `${userContent}\\n（附：${cellRef.label}）`
      : userContent;

    const sentAttachments = attachments.map(messageAttachment);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: shownContent, attachments: sentAttachments },
      // 占位气泡。这条链路首字要二十几秒，没有它学生会对着空白以为没发出去。
      { role: "assistant", content: "", streaming: true },
    ]);
    onClearCellRef?.();
    setInput("");"""

PANEL_PAYLOAD_OLD = """    const payload: StartTurnMessage = {
      type: "start_turn",
      content: userContent,"""

PANEL_PAYLOAD_NEW = """    const payload: StartTurnMessage = {
      type: "start_turn",
      content: outgoing,"""

# 占位气泡的渲染：内容为空且还在流式中，就显示一句「正在读这一页」
PANEL_RENDER_OLD = """                  {m.role === "assistant" ? (
                    <AssistantResponse
                      content={m.content}
                      className="text-sm leading-relaxed"
                      isStreaming={Boolean(m.streaming)}
                    />
                  ) : ("""

PANEL_RENDER_NEW = """                  {m.role === "assistant" ? (
                    m.streaming && !m.content ? (
                      <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        助教正在读这一页，通常要二十几秒…
                      </div>
                    ) : (
                      <AssistantResponse
                        content={m.content}
                        className="text-sm leading-relaxed"
                        isStreaming={Boolean(m.streaming)}
                      />
                    )
                  ) : ("""

# 输入框上方的引用卡片
PANEL_CHIP_ANCHOR = """        {attachmentError && (
          <div className="mb-2 text-[11px] text-red-500">{attachmentError}</div>
        )}"""

PANEL_CHIP_NEW = """        {attachmentError && (
          <div className="mb-2 text-[11px] text-red-500">{attachmentError}</div>
        )}
        {cellRef && (
          <div className="mb-2 rounded-xl border border-[var(--primary)]/30 bg-[var(--primary)]/5">
            <div className="flex items-center gap-2 px-2 py-1.5">
              <Code2 className="h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
              <button
                type="button"
                onClick={() => setCellRefOpen((v) => !v)}
                className="min-w-0 flex-1 truncate text-left text-[11px] text-[var(--foreground)]"
                title={cellRefOpen ? "收起代码" : "展开看看引用了什么"}
              >
                {cellRef.label} · {cellRef.code.split("\\n").length} 行
                {cellRef.error ? " · 有报错" : ""}
                <span className="ml-1 text-[var(--muted-foreground)]">
                  {cellRefOpen ? "收起" : "展开"}
                </span>
              </button>
              <button
                type="button"
                onClick={() => onClearCellRef?.()}
                className="shrink-0 opacity-60 hover:opacity-100"
                title="不带这段代码"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
            {cellRefOpen && (
              <pre className="max-h-40 overflow-auto border-t border-[var(--primary)]/20 px-2 py-1.5 text-[10px] leading-relaxed text-[var(--muted-foreground)]">
                {cellRef.code}
              </pre>
            )}
          </div>
        )}"""

PANEL_TEXTAREA_OLD = """          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t("Ask about this page…")}
            rows={1}"""

PANEL_TEXTAREA_NEW = """          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              cellRef
                ? "对这一格提问，比如：这里为什么要用字典？"
                : t("Ask about this page…")
            }
            rows={1}"""

PANEL_TEXTAREA_CLASS_OLD = (
    '            className="max-h-32 min-h-8 flex-1 resize-none bg-transparent '
    'px-1 py-1.5 text-sm text-[var(--foreground)] outline-none '
    'placeholder:text-[var(--muted-foreground)]"'
)
PANEL_TEXTAREA_CLASS_NEW = (
    '            className="max-h-44 min-h-8 flex-1 resize-none overflow-y-auto '
    'bg-transparent px-1 py-1.5 text-sm text-[var(--foreground)] outline-none '
    'placeholder:text-[var(--muted-foreground)]"'
)

PANEL_SUBMIT_OLD = """            disabled={
              busy ||
              (!input.trim() && attachments.length === 0) ||
              !book ||
              !page
            }"""
PANEL_SUBMIT_NEW = """            disabled={
              busy ||
              (!input.trim() && attachments.length === 0 && !cellRef) ||
              !book ||
              !page
            }"""

# ── page.tsx ─────────────────────────────────────────────────────────────

PAGE_STATE_OLD = '''  const [chatOpen, setChatOpen] = useState(false);
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

PAGE_STATE_NEW = '''  const [chatOpen, setChatOpen] = useState(false);
  const [cellRef, setCellRef] = useState<CellReference | null>(null);

  // 可运行单元格上的「问助教」按钮派发这个事件，带着那一格的代码与运行结果。
  // 这里只把它存成一条引用，不去替学生写问题——问题该由他自己写。
  useEffect(() => {
    function onAskAboutCell(event: Event) {
      const detail = (event as CustomEvent).detail || {};
      setCellRef({
        label: detail.cellIndex ? `第 ${detail.cellIndex} 格代码` : "这一格代码",
        code: String(detail.code || ""),
        output: String(detail.stdout || detail.textResult || ""),
        error: String(detail.error || ""),
      });
      setChatOpen(true);
    }
    window.addEventListener("ext:ask-about-cell", onAskAboutCell);
    return () => window.removeEventListener("ext:ask-about-cell", onAskAboutCell);
  }, []);'''

PAGE_PANEL_OLD = """            prefill={cellQuestion}
          />"""
PAGE_PANEL_NEW = """            cellRef={cellRef}
            onClearCellRef={() => setCellRef(null)}
          />"""


def patch(path: Path, pairs: list[tuple[str, str]]) -> bool:
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in text:
            continue
        if old not in text:
            print(f"在 {path} 里没找到要替换的片段，请人工确认：\n{old[:90]}…")
            return False
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return True


def ensure_import(path: Path, symbol: str, module: str) -> None:
    """确保文件从 *module* 里导入了 *symbol*。单行和多行两种导入写法都认。"""
    text = path.read_text(encoding="utf-8")
    head = text.split("\n\n\n")[0]

    # 单行：import { A, B } from "mod";
    for line in head.splitlines():
        if line.startswith("import {") and f'from "{module}"' in line:
            if symbol in line:
                return
            text = text.replace(line, line.replace("import {", f"import {{ {symbol},", 1), 1)
            path.write_text(text, encoding="utf-8")
            return

    # 多行：import {\n  A,\n  B,\n} from "mod";
    closing = f'}} from "{module}";'
    if closing in head:
        block_start = head.rfind("import {", 0, head.index(closing))
        block = head[block_start : head.index(closing) + len(closing)]
        if f"  {symbol}," in block:
            return
        text = text.replace(closing, f"  {symbol},\n{closing}", 1)
        path.write_text(text, encoding="utf-8")
        return

    print(f"提醒：{path} 里没找到 {module} 的导入行，{symbol} 需要人工补。")


def main() -> int:
    panel = BOOK / "components/BookChatPanel.tsx"
    page = BOOK / "page.tsx"

    ok = patch(
        panel,
        [
            (PANEL_PROP_OLD, PANEL_PROP_NEW),
            (PANEL_ARGS_OLD, PANEL_ARGS_NEW),
            (PANEL_STATE_OLD, PANEL_STATE_NEW),
            (PANEL_SEND_OLD, PANEL_SEND_NEW),
            (PANEL_PAYLOAD_OLD, PANEL_PAYLOAD_NEW),
            (PANEL_RENDER_OLD, PANEL_RENDER_NEW),
            (PANEL_CHIP_ANCHOR, PANEL_CHIP_NEW),
            (PANEL_TEXTAREA_OLD, PANEL_TEXTAREA_NEW),
            (PANEL_TEXTAREA_CLASS_OLD, PANEL_TEXTAREA_CLASS_NEW),
            (PANEL_SUBMIT_OLD, PANEL_SUBMIT_NEW),
        ],
    )
    if not ok:
        return 1

    ensure_import(panel, "Code2", "lucide-react")
    ensure_import(panel, "Loader2", "lucide-react")
    ensure_import(panel, "useRef", "react")

    ok = patch(page, [(PAGE_STATE_OLD, PAGE_STATE_NEW), (PAGE_PANEL_OLD, PAGE_PANEL_NEW)])
    if not ok:
        return 1

    # page.tsx 要能引用面板导出的 CellReference 类型
    text = page.read_text(encoding="utf-8")
    if "CellReference" in text and "type CellReference" not in text:
        needle = 'import BookChatPanel from "./components/BookChatPanel";'
        if needle in text:
            text = text.replace(
                needle,
                'import BookChatPanel, {\n  type CellReference,\n} from "./components/BookChatPanel";',
                1,
            )
            page.write_text(text, encoding="utf-8")
        else:
            print("提醒：page.tsx 里没找到 BookChatPanel 的导入行，类型需要人工补。")

    print("「问助教」已改成引用卡片：代码不再占输入框，输入框会自动增高，等待时有提示。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
