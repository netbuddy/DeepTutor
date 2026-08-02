#!/usr/bin/env python3
"""让书页问答面板也显示思考过程与执行步骤。在 ~/DeepTutor-src 下执行。

主界面的对话窗口用 AssistantActivity 展示一次回答的中间过程：正在探查哪些资料、
调了什么工具、每一步花了多久，可以展开细看。书页侧边的问答面板本来只显示最终答案，
中间二十几秒里什么都没有，学生不知道它是在干活还是卡住了。

面板其实已经把每条流式事件存在消息的 events 字段里了，只是没渲染。这里把主界面那个
组件直接接上去，顺便撤掉上一版那个手写的「助教正在读这一页」占位——
有真实步骤可看，就不需要一句笼统的话。

接上去之后暴露出两个连带问题，不一起修的话步骤根本看不到：

一、**本轮刚建的会话会把正在流式输出的消息清掉。** 面板发出第一个问题时后端才创建
会话，父组件拿到 id 后回填成 initialSessionId；面板那个「换会话就重置」的副作用
因此在回答进行到一半时触发，把 messages 清空再从服务端重拉——正在积累的步骤
一起没了。判据要收窄：只有真的换了书页或换了会话才重置，自己刚创建的那个不算。

二、**用户气泡会被引用的代码撑满。** 发给模型的内容里带着引用那一格的代码，
服务端存的就是这份内容，重新打开会话时会原样回显。这里把用户消息里的代码块
折叠起来，默认只显示问题本身。
"""

from pathlib import Path

PANEL = Path("web/app/(workspace)/book/components/BookChatPanel.tsx")

IMPORT_ANCHOR = 'import AssistantResponse from "@/components/common/AssistantResponse";'
IMPORT_NEW = '''import AssistantResponse from "@/components/common/AssistantResponse";
import { AssistantActivity } from "@/components/chat/home/TracePanels";'''

RENDER_OLD = """                  {m.role === "assistant" ? (
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

RENDER_NEW = """                  {m.role === "assistant" ? (
                    <>
                      {/* 思考过程与执行步骤。和主界面用的是同一个组件：
                          干活时自动展开，答完自动收起，点一下可以钉住。 */}
                      <AssistantActivity
                        events={m.events || []}
                        isStreaming={Boolean(m.streaming)}
                        content={m.content}
                        className="mb-2"
                      />
                      {m.content ? (
                        <AssistantResponse
                          content={m.content}
                          className="text-sm leading-relaxed"
                          isStreaming={Boolean(m.streaming)}
                        />
                      ) : null}
                    </>
                  ) : ("""


# ── 连带问题一：别把自己刚创建的会话当成「换了会话」 ──────────────────────

RESET_OLD = """  useEffect(() => {
    let cancelled = false;
    retryTimersRef.current.forEach((timer) => clearTimeout(timer));"""

RESET_NEW = """  const spotRef = useRef<string>("");

  useEffect(() => {
    // 这一轮问答刚把会话建起来，父组件随后把 id 回填进 initialSessionId。
    // 那不是「换了会话」，不能把正在流式输出的消息清掉再从服务端重拉——
    // 一拉就把刚积累起来的思考步骤和半截答案冲掉了。
    const spot = `${book?.id || ""}|${page?.id || ""}`;
    const sameSpot = spot === spotRef.current;
    const sameSession =
      Boolean(initialSessionId) && initialSessionId === sessionIdRef.current;
    spotRef.current = spot;
    if (sameSpot && sameSession) return;

    let cancelled = false;
    retryTimersRef.current.forEach((timer) => clearTimeout(timer));"""

# ── 连带问题二：用户气泡里的代码块折叠起来 ──────────────────────────────

USER_RENDER_OLD = """                  ) : (
                    <div className="whitespace-pre-wrap break-words">
                      {m.content}
                    </div>
                  )}"""

USER_RENDER_NEW = """                  ) : (
                    <UserMessageBody content={m.content} />
                  )}"""

USER_BODY_ANCHOR = "export default function BookChatPanel({"

USER_BODY_NEW = '''/** 用户消息体。带代码块的（「问助教」引用的那一格）默认折叠，只显示问题本身。
 *
 * 发给模型的内容里必须带上代码，服务端存的也是这一份，重新打开会话时会原样回显。
 * 折叠是显示层的事，不改动存下来的内容——改内容会让「发出去的」和「存下来的」对不上。
 */
function UserMessageBody({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const fenceAt = content.indexOf("\\n```");
  if (fenceAt < 0) {
    return <div className="whitespace-pre-wrap break-words">{content}</div>;
  }
  const head = content.slice(0, fenceAt).trimEnd();
  const body = content.slice(fenceAt).trim();
  const lineCount = body.split("\\n").length;
  return (
    <div>
      <div className="whitespace-pre-wrap break-words">{head}</div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mt-1 text-[11px] underline decoration-dotted opacity-80 hover:opacity-100"
      >
        {open ? "收起附带的代码" : `附带了 ${lineCount} 行代码，点开看看`}
      </button>
      {open && (
        <pre className="mt-1 max-h-56 overflow-auto rounded-lg bg-black/15 p-2 text-[10px] leading-relaxed">
          {body}
        </pre>
      )}
    </div>
  );
}

export default function BookChatPanel({'''


def main() -> int:
    text = PANEL.read_text(encoding="utf-8")

    if IMPORT_NEW not in text:
        if IMPORT_ANCHOR not in text:
            print("没找到 AssistantResponse 的导入行，请人工确认。")
            return 1
        text = text.replace(IMPORT_ANCHOR, IMPORT_NEW, 1)

    if RENDER_NEW not in text:
        if RENDER_OLD not in text:
            print("没找到助手气泡的渲染片段，请先执行 patch_ask.py。")
            return 1
        text = text.replace(RENDER_OLD, RENDER_NEW, 1)

    if RESET_NEW not in text:
        if RESET_OLD not in text:
            print("没找到会话重置的副作用，请人工确认。")
            return 1
        text = text.replace(RESET_OLD, RESET_NEW, 1)

    if USER_RENDER_NEW not in text:
        if USER_RENDER_OLD not in text:
            print("没找到用户气泡的渲染片段，请人工确认。")
            return 1
        text = text.replace(USER_RENDER_OLD, USER_RENDER_NEW, 1)

    if "function UserMessageBody(" not in text:
        text = text.replace(USER_BODY_ANCHOR, USER_BODY_NEW, 1)

    PANEL.write_text(text, encoding="utf-8")
    print("书页问答面板已接上思考过程与执行步骤，并修好会话回填冲掉消息、用户气泡被代码撑满两处。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
