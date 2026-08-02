"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type {
  ChangeEvent,
  ClipboardEvent,
  KeyboardEvent,
  MouseEvent as ReactMouseEvent,
} from "react";
import {
  FileText,
  Loader2,
  MessageSquare,
  Paperclip,
  Send,
  X,
  Code2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import AssistantResponse from "@/components/common/AssistantResponse";
import { AssistantActivity } from "@/components/chat/home/TracePanels";
import { useAppShell } from "@/context/AppShellContext";
import { getSession } from "@/lib/session-api";
import {
  ATTACHMENT_ACCEPT,
  classifyFile,
  formatBytes,
} from "@/lib/doc-attachments";
import { useAttachmentLimits } from "@/lib/attachment-limits";
import {
  extractBase64FromDataUrl,
  readFileAsDataUrl,
} from "@/lib/file-attachments";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import { useImeComposing } from "@/lib/use-ime-composing";
import { shouldAppendEventContent } from "@/lib/stream";
import {
  UnifiedWSClient,
  type StartTurnMessage,
  type StreamEvent,
} from "@/lib/unified-ws";
import type { MessageAttachment } from "@/context/UnifiedChatContext";
import type { Page, Book } from "@/lib/book-types";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  attachments?: MessageAttachment[];
  events?: StreamEvent[];
}

interface PendingAttachment {
  type: "image" | "file" | "pdf";
  filename: string;
  base64: string;
  mimeType: string;
  size: number;
}

export interface BookChatPanelProps {
  book: Book | null;
  page: Page | null;
  open: boolean;
  onClose: () => void;
  initialSessionId?: string | null;
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
};

function attachmentTypeFor(file: File): PendingAttachment["type"] | null {
  const kind = classifyFile(file);
  if (!kind) return null;
  if (kind === "image") return "image";
  return file.type === "application/pdf" ||
    file.name.toLowerCase().endsWith(".pdf")
    ? "pdf"
    : "file";
}

function outgoingAttachment(attachment: PendingAttachment) {
  return {
    type: attachment.type,
    filename: attachment.filename,
    base64: attachment.base64,
    mime_type: attachment.mimeType,
  };
}

function messageAttachment(attachment: PendingAttachment): MessageAttachment {
  return {
    type: attachment.type,
    filename: attachment.filename,
    base64: attachment.base64,
    mime_type: attachment.mimeType,
  };
}

/** 用户消息体。带代码块的（「问助教」引用的那一格）默认折叠，只显示问题本身。
 *
 * 发给模型的内容里必须带上代码，服务端存的也是这一份，重新打开会话时会原样回显。
 * 折叠是显示层的事，不改动存下来的内容——改内容会让「发出去的」和「存下来的」对不上。
 */
function UserMessageBody({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const fenceAt = content.indexOf("\n```");
  if (fenceAt < 0) {
    return <div className="whitespace-pre-wrap break-words">{content}</div>;
  }
  const head = content.slice(0, fenceAt).trimEnd();
  const body = content.slice(fenceAt).trim();
  const lineCount = body.split("\n").length;
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

export default function BookChatPanel({
  book,
  page,
  open,
  onClose,
  initialSessionId = null,
  onSessionResolved,
  cellRef = null,
  onClearCellRef,
}: BookChatPanelProps) {
  const { t } = useTranslation();
  const { language: appLanguage } = useAppShell();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
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
  }, [input]);
  const [busy, setBusy] = useState(false);
  const [width, setWidth] = useState(360);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const attachmentLimits = useAttachmentLimits();
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const clientRef = useRef<UnifiedWSClient | null>(null);
  const retryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const { isComposingRef, onCompositionStart, onCompositionEnd } =
    useImeComposing();

  useEffect(() => {
    const raw = window.localStorage.getItem("deeptutor.bookChat.width");
    const parsed = Number(raw);
    if (Number.isFinite(parsed) && parsed >= 300 && parsed <= 720) {
      // Hydrate persisted panel width after the SSR-safe default render.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setWidth(parsed);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem("deeptutor.bookChat.width", String(width));
  }, [width]);

  useEffect(() => {
    const retryTimers = retryTimersRef.current;
    return () => {
      retryTimers.forEach((timer) => clearTimeout(timer));
      retryTimers.clear();
      clientRef.current?.disconnect();
      clientRef.current = null;
    };
  }, []);

  const spotRef = useRef<string>("");

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
    retryTimersRef.current.forEach((timer) => clearTimeout(timer));
    retryTimersRef.current.clear();
    clientRef.current?.disconnect();
    clientRef.current = null;
    sessionIdRef.current = initialSessionId || null;
    // Reset local chat state when the backing page/session changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMessages([]);
    setAttachments([]);
    setAttachmentError(null);
    setBusy(false);

    if (!open || !initialSessionId) return;
    void getSession(initialSessionId)
      .then((session) => {
        if (cancelled) return;
        const restored = (session.messages || [])
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            role: m.role as "user" | "assistant",
            content: String(m.content || ""),
            attachments: m.attachments || [],
            events: m.events || [],
          }));
        setMessages(restored);
      })
      .catch(() => {
        if (!cancelled) sessionIdRef.current = null;
      });

    return () => {
      cancelled = true;
    };
  }, [book?.id, page?.id, initialSessionId, open]);

  // Pin-to-bottom in layout phase (not in a post-paint effect): the
  // assignment lands before the browser commits the frame so the
  // viewer never sees the "new content at the old scrollTop" flash
  // that an ordinary ``useEffect`` would produce during fast streams.
  useLayoutEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages]);

  function handleEvent(event: StreamEvent) {
    if (event.type === "session") {
      const metadata = (event.metadata || {}) as Record<string, unknown>;
      const sessionId =
        typeof metadata.session_id === "string"
          ? metadata.session_id
          : typeof event.session_id === "string"
            ? event.session_id
            : "";
      if (sessionId) {
        sessionIdRef.current = sessionId;
        onSessionResolved?.(sessionId);
      }
      return;
    }

    if (event.type === "done") {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, streaming: false };
        }
        return next;
      });
      setBusy(false);
      return;
    }

    if (event.type === "error") {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: event.content || t("Error"),
          streaming: false,
        },
      ]);
      setBusy(false);
      return;
    }

    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      const contentDelta = shouldAppendEventContent(event)
        ? event.content || ""
        : "";
      if (last && last.role === "assistant" && last.streaming) {
        next[next.length - 1] = {
          ...last,
          content: last.content + contentDelta,
          events: [...(last.events || []), event],
        };
      } else if (contentDelta || event.type !== "content") {
        next.push({
          role: "assistant",
          content: contentDelta,
          streaming: true,
          events: [event],
        });
      }
      return next;
    });
  }

  function ensureClient(): UnifiedWSClient {
    if (clientRef.current) return clientRef.current;
    const client = new UnifiedWSClient(handleEvent, () => setBusy(false));
    clientRef.current = client;
    client.connect();
    return client;
  }

  function sendWithRetry(
    client: UnifiedWSClient,
    payload: StartTurnMessage,
    attempt = 0,
  ) {
    if (client.connected) {
      client.send(payload);
      return;
    }
    if (attempt >= 10) {
      setBusy(false);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: t("Connection failed. Please try again."),
        },
      ]);
      return;
    }
    const timer = setTimeout(() => {
      retryTimersRef.current.delete(timer);
      sendWithRetry(client, payload, attempt + 1);
    }, 200);
    retryTimersRef.current.add(timer);
  }

  function beginResize(event: ReactMouseEvent<HTMLDivElement>) {
    event.preventDefault();
    dragRef.current = { startX: event.clientX, startWidth: width };
    const onMove = (moveEvent: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const next = Math.max(
        300,
        Math.min(720, drag.startWidth + drag.startX - moveEvent.clientX),
      );
      setWidth(next);
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  function filterFiles(files: File[]): File[] {
    setAttachmentError(null);
    const currentTotal = attachments.reduce((sum, file) => sum + file.size, 0);
    let nextTotal = currentTotal;
    const accepted: File[] = [];
    for (const file of files) {
      const type = attachmentTypeFor(file);
      if (!type) {
        setAttachmentError(t("Unsupported file type."));
        continue;
      }
      if (file.size > attachmentLimits.maxFileBytes) {
        setAttachmentError(
          t("File is too large ({{size}}).", { size: formatBytes(file.size) }),
        );
        continue;
      }
      if (nextTotal + file.size > attachmentLimits.maxTotalBytes) {
        setAttachmentError(t("Attachments exceed the total upload limit."));
        continue;
      }
      nextTotal += file.size;
      accepted.push(file);
    }
    return accepted;
  }

  async function addFiles(files: File[]) {
    const accepted = filterFiles(files);
    if (!accepted.length) return;
    const next = await Promise.all(
      accepted.map(async (file) => {
        const dataUrl = await readFileAsDataUrl(file);
        return {
          type: attachmentTypeFor(file) || "file",
          filename: file.name,
          base64: extractBase64FromDataUrl(dataUrl),
          mimeType: file.type || "application/octet-stream",
          size: file.size,
        } satisfies PendingAttachment;
      }),
    );
    setAttachments((prev) => [...prev, ...next]);
  }

  function handleFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files || []);
    if (picked.length) void addFiles(picked);
    event.target.value = "";
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.files || []);
    if (!files.length) return;
    event.preventDefault();
    void addFiles(files);
  }

  async function send() {
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
          .join("\n")
      : userContent;
    const shownContent = cellRef
      ? `${userContent}\n（附：${cellRef.label}）`
      : userContent;

    const sentAttachments = attachments.map(messageAttachment);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: shownContent, attachments: sentAttachments },
      // 占位气泡。这条链路首字要二十几秒，没有它学生会对着空白以为没发出去。
      { role: "assistant", content: "", streaming: true },
    ]);
    onClearCellRef?.();
    setInput("");
    setAttachments([]);
    setAttachmentError(null);
    setBusy(true);

    const client = ensureClient();
    const payload: StartTurnMessage = {
      type: "start_turn",
      content: outgoing,
      session_id: sessionIdRef.current,
      capability: "chat",
      tools: book.knowledge_bases?.length ? ["rag"] : [],
      knowledge_bases: book.knowledge_bases || [],
      attachments: attachments.map(outgoingAttachment),
      language: appLanguage,
      book_references: [{ book_id: book.id, page_ids: [page.id] }],
    };
    sendWithRetry(client, payload);
  }

  if (!open) return null;

  return (
    <aside
      className="relative flex h-full shrink-0 flex-col border-l border-[var(--border)] bg-[var(--card)]/40 backdrop-blur"
      style={{ width }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        title={t("Drag to resize")}
        onMouseDown={beginResize}
        className="absolute inset-y-0 left-0 z-10 w-1 cursor-col-resize bg-transparent transition-colors hover:bg-[var(--primary)]/30"
      />
      <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <MessageSquare className="h-4 w-4 text-[var(--primary)]" />
            {t("Page Chat")}
          </div>
          {page?.title && (
            <div className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">
              {t("Context")}: {page.title}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div
        ref={scrollerRef}
        data-chat-scroll-root="true"
        className="flex-1 overflow-y-auto px-4 py-3"
      >
        {messages.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/50 p-4 text-xs leading-5 text-[var(--muted-foreground)]">
            {t(
              "Ask a question about this page. The current chapter content is sent to the assistant automatically.",
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "user" ? "flex justify-end" : "flex justify-start"
                }
              >
                <div
                  className={
                    m.role === "user"
                      ? "max-w-[82%] rounded-2xl rounded-tr-sm bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] shadow-sm"
                      : "max-w-[88%] rounded-2xl rounded-tl-sm bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] shadow-sm"
                  }
                >
                  {m.role === "user" && (
                    <div className="mb-1 text-right text-[10px] font-medium uppercase tracking-wide opacity-75">
                      {t("You")}
                    </div>
                  )}
                  {m.attachments?.length ? (
                    <div className="mb-2 flex flex-wrap justify-end gap-1.5">
                      {m.attachments.map((attachment, idx) => (
                        <span
                          key={`${attachment.filename || idx}-${idx}`}
                          className="inline-flex max-w-full items-center gap-1 rounded-lg bg-black/10 px-2 py-1 text-[10px]"
                        >
                          <FileText className="h-3 w-3 shrink-0" />
                          <span className="truncate">
                            {attachment.filename || t("Attachment")}
                          </span>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {m.role === "assistant" ? (
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
                  ) : (
                    <UserMessageBody content={m.content} />
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        className="border-t border-[var(--border)] p-3"
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ATTACHMENT_ACCEPT}
          onChange={handleFileInputChange}
          className="hidden"
          aria-hidden="true"
          tabIndex={-1}
        />
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {attachments.map((attachment, index) => (
              <span
                key={`${attachment.filename}-${index}`}
                className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[11px] text-[var(--foreground)]"
              >
                <FileText className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
                <span className="truncate">{attachment.filename}</span>
                <button
                  type="button"
                  onClick={() =>
                    setAttachments((prev) => prev.filter((_, i) => i !== index))
                  }
                  className="opacity-60 hover:opacity-100"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        {attachmentError && (
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
                {cellRef.label} · {cellRef.code.split("\n").length} 行
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
        )}
        <div className="flex items-end gap-2 rounded-2xl border border-[var(--border)] bg-[var(--background)] px-2 py-2 focus-within:border-[var(--primary)]/50 focus-within:ring-2 focus-within:ring-[var(--primary)]/10">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mb-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            title={t("Attach files")}
            aria-label={t("Attach files")}
          >
            <Paperclip className="h-4 w-4" />
          </button>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              cellRef
                ? "对这一格提问，比如：这里为什么要用字典？"
                : t("Ask about this page…")
            }
            rows={1}
            onPaste={handlePaste}
            onCompositionStart={onCompositionStart}
            onCompositionEnd={onCompositionEnd}
            onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
              if (shouldSubmitOnEnter(e, isComposingRef.current)) {
                e.preventDefault();
                void send();
              }
            }}
            className="max-h-44 min-h-8 flex-1 resize-none overflow-y-auto bg-transparent px-1 py-1.5 text-sm text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
          />
          <button
            type="submit"
            disabled={
              busy ||
              (!input.trim() && attachments.length === 0 && !cellRef) ||
              !book ||
              !page
            }
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
      </form>
    </aside>
  );
}
