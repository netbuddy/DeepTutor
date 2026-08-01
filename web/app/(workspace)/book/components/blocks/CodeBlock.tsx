"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Block } from "@/lib/book-types";

import RunnableCell from "./RunnableCell";

export interface CodeBlockProps {
  block: Block;
  bookId?: string;
  pageId?: string;
}

export default function CodeBlock({ block, bookId, pageId }: CodeBlockProps) {
  const language = String(block.payload?.language || "python");
  const code = String(block.payload?.code || "");
  const explanation = String(block.payload?.explanation || "");

  // 从课程导入的 notebook 单元格会在 payload 里带一段 notebook 信息，这类格子能真运行。
  // 其余代码块（例如书里由模型写出来的示例）保持原来的静态展示。
  const notebook = block.payload?.notebook as { runnable?: boolean } | undefined;
  if (notebook?.runnable && bookId && pageId) {
    return (
      <RunnableCell
        blockId={block.id}
        bookId={bookId}
        pageId={pageId}
        code={code}
        language={language}
        notebook={block.payload.notebook as never}
      />
    );
  }

  const fenced = "```" + language + "\n" + code + "\n```";
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <MarkdownRenderer content={fenced} variant="default" />
      {explanation && (
        <p className="mt-2 text-xs text-[var(--muted-foreground)]">
          {explanation}
        </p>
      )}
    </div>
  );
}
