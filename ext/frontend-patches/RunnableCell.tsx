"use client";

/**
 * 可运行的 notebook 单元格。
 *
 * 课程导入时，notebook 的每个代码格都变成一个 code 块，块的 payload 里多挂了一段
 * notebook 信息（源文件、执行时的工作目录、这是第几格）。认得那段信息的格子就用这个
 * 组件渲染：代码可改、可运行、输出就地显示，还能就这一格向助教提问。
 *
 * 执行发生在服务器上一个独立容器里的长驻内核中，同一页共用一个内核，所以靠前的格子
 * 定义的变量，靠后的格子能直接用——这正是 notebook 的教学价值所在。反过来，跳着运行
 * 会撞上「变量没定义」，所以这里给了一个「从头运行到这一格」的按钮。
 */

import { useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CornerDownRight,
  Loader2,
  MessageSquarePlus,
  Play,
  RotateCcw,
  Undo2,
} from "lucide-react";
import { apiUrl } from "@/lib/api";

interface NotebookMeta {
  source?: string;
  cwd?: string;
  cell_index?: number;
  runnable?: boolean;
  saved_output?: string;
  saved_image_count?: number;
}

interface CellImage {
  url: string;
  path: string;
  mime: string;
  bytes: number;
}

interface RunResult {
  status: "ok" | "error" | "timeout";
  stdout: string;
  stderr: string;
  text_result: string;
  html: string;
  images: CellImage[];
  error: { ename: string; evalue: string; traceback: string } | null;
  elapsed_s: number;
  preceding?: { block_id: string; status: string; cell_index?: number }[];
}

export interface RunnableCellProps {
  blockId: string;
  bookId: string;
  pageId: string;
  code: string;
  language: string;
  notebook: NotebookMeta;
}

/**
 * 表格类输出是内核返回的 HTML（pandas 就是这么呈现 DataFrame 的），这里要原样插进页面。
 * 内容来自学生自己运行的代码，但仍然把脚本和事件属性剥掉：万一学生照着别处贴来的代码
 * 运行，不该让它顺手在页面上执行脚本。
 */
function sanitizeHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, "")
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, "")
    .replace(/\son\w+\s*=\s*'[^']*'/gi, "")
    .replace(/javascript:/gi, "");
}

export default function RunnableCell({
  blockId,
  bookId,
  pageId,
  code: originalCode,
  language,
  notebook,
}: RunnableCellProps) {
  const [code, setCode] = useState(originalCode);
  const [running, setRunning] = useState<"" | "single" | "through">("");
  const [result, setResult] = useState<RunResult | null>(null);
  const [failure, setFailure] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const edited = code !== originalCode;
  const cellLabel = notebook.cell_index ? `第 ${notebook.cell_index} 格` : "代码";
  const lineCount = useMemo(() => code.split("\n").length, [code]);

  async function run(through: boolean) {
    setRunning(through ? "through" : "single");
    setFailure("");
    try {
      const response = await fetch(apiUrl("/api/v1/ext/notebook/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_id: bookId,
          page_id: pageId,
          block_id: blockId,
          code,
          through,
        }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        setFailure(detail?.detail || `运行失败（HTTP ${response.status}）`);
        return;
      }
      setResult(await response.json());
    } catch (error) {
      setFailure(
        `连不上后端：${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setRunning("");
    }
  }

  async function resetKernel() {
    setFailure("");
    try {
      await fetch(apiUrl("/api/v1/ext/notebook/reset"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book_id: bookId, page_id: pageId }),
      });
      setResult(null);
    } catch (error) {
      setFailure(
        `重置失败：${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  function askTutor() {
    // 面板由页面那一层打开，这里只负责把这一格的上下文递出去。用自定义事件而不是
    // 逐层传回调，是为了让本地改动集中在尽量少的文件里，升级变基时好合。
    window.dispatchEvent(
      new CustomEvent("ext:ask-about-cell", {
        detail: {
          blockId,
          cellIndex: notebook.cell_index,
          source: notebook.source,
          code,
          stdout: result?.stdout ?? "",
          textResult: result?.text_result ?? "",
          error: result?.error
            ? `${result.error.ename}: ${result.error.evalue}`
            : "",
        },
      }),
    );
  }

  const busy = running !== "";

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--muted)]/40 px-3 py-1.5">
        <span className="font-mono text-xs text-[var(--muted-foreground)]">
          {cellLabel}
        </span>
        {edited && (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">
            已修改
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => void run(false)}
            disabled={busy}
            title="只运行这一格。它可能依赖前面格子里定义的变量。"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
          >
            {running === "single" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            运行
          </button>
          <button
            type="button"
            onClick={() => void run(true)}
            disabled={busy}
            title="从这一页的第一格依次运行到这一格。变量没定义时用它。"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
          >
            {running === "through" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CornerDownRight className="h-3.5 w-3.5" />
            )}
            从头跑到这
          </button>
          {edited && (
            <button
              type="button"
              onClick={() => setCode(originalCode)}
              title="把代码改回课程原本的写法"
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              <Undo2 className="h-3.5 w-3.5" />
              还原
            </button>
          )}
          <button
            type="button"
            onClick={() => void resetKernel()}
            disabled={busy}
            title="清空这一页已经运行出来的所有变量，从干净的环境重新开始"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            重置
          </button>
          <button
            type="button"
            onClick={askTutor}
            title="把这一格的代码和运行结果发给助教提问"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
            问助教
          </button>
        </div>
      </div>

      <textarea
        ref={textareaRef}
        value={code}
        onChange={(event) => setCode(event.target.value)}
        spellCheck={false}
        rows={Math.min(Math.max(lineCount, 2), 28)}
        aria-label={`${cellLabel}的代码，可以直接改`}
        className="w-full resize-y bg-transparent px-3 py-2 font-mono text-[13px] leading-relaxed text-[var(--foreground)] outline-none focus:bg-[var(--muted)]/20"
      />

      {failure && (
        <div className="flex items-start gap-2 border-t border-[var(--border)] bg-red-500/5 px-3 py-2 text-xs text-red-600 dark:text-red-400">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{failure}</span>
        </div>
      )}

      {result && (
        <div className="border-t border-[var(--border)] px-3 py-2 text-[13px]">
          <div className="mb-1 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
            输出
            <span>{result.elapsed_s.toFixed(2)}s</span>
            {result.status === "timeout" && (
              <span className="text-amber-600 dark:text-amber-400">执行超时</span>
            )}
            {result.preceding && result.preceding.length > 0 && (
              <span>（先跑了前面 {result.preceding.length} 格）</span>
            )}
          </div>

          {result.stdout.trim() && (
            <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[12px] text-[var(--foreground)]">
              {result.stdout}
            </pre>
          )}

          {result.html ? (
            <div
              className="ext-cell-html overflow-x-auto"
              dangerouslySetInnerHTML={{ __html: sanitizeHtml(result.html) }}
            />
          ) : (
            result.text_result.trim() && (
              <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[12px] text-[var(--foreground)]">
                {result.text_result}
              </pre>
            )
          )}

          {result.images.map((image) => (
            <img
              key={image.url}
              src={apiUrl(image.url)}
              alt="这一格画出来的图"
              className="my-2 max-w-full rounded-lg border border-[var(--border)]"
            />
          ))}

          {result.stderr.trim() && !result.error && (
            <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[12px] text-amber-700 dark:text-amber-400">
              {result.stderr}
            </pre>
          )}

          {result.error && (
            <div className="rounded-lg bg-red-500/5 p-2">
              <div className="font-mono text-[12px] font-semibold text-red-600 dark:text-red-400">
                {result.error.ename}: {result.error.evalue}
              </div>
              {result.error.traceback && (
                <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-red-700/80 dark:text-red-300/80">
                  {result.error.traceback}
                </pre>
              )}
              <div className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
                {result.error.ename === "NameError"
                  ? "这一格用到了前面格子里定义的变量。点「从头跑到这」就能补上。"
                  : "看不懂这个报错？点右上角「问助教」，代码和报错会一起发过去。"}
              </div>
            </div>
          )}
        </div>
      )}

      {!result && notebook.saved_output && (
        <div className="border-t border-[var(--border)] px-3 py-2">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
            课程里存的运行结果
          </div>
          <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[12px] text-[var(--muted-foreground)]">
            {notebook.saved_output}
          </pre>
          {notebook.saved_image_count ? (
            <div className="text-[11px] text-[var(--muted-foreground)]">
              这一格原本还画了 {notebook.saved_image_count} 张图，点运行可以重新生成。
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
