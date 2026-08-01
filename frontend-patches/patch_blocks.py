#!/usr/bin/env python3
"""把 Book 的代码块接上「可运行」能力。在 ~/DeepTutor-src 下执行。

只动两个文件：CodeBlock 按 payload 里有没有 notebook 信息分派，BlockRenderer 把
书与页的标识传下去。改动面小是有意的——这是唯一必须落在宿主源码里的部分，
每次升级都要变基，改得越集中越好合。
"""

from pathlib import Path

BLOCKS = Path("web/app/(workspace)/book/components/blocks")

CODE_BLOCK = '''"use client";

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

  const fenced = "```" + language + "\\n" + code + "\\n```";
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
'''

OLD_DISPATCH = "      body = <CodeBlock block={block} />;"
NEW_DISPATCH = (
    "      body = (\n"
    "        <CodeBlock block={block} bookId={bookId} pageId={currentPageId} />\n"
    "      );"
)


def main() -> int:
    (BLOCKS / "CodeBlock.tsx").write_text(CODE_BLOCK, encoding="utf-8")

    renderer = BLOCKS / "BlockRenderer.tsx"
    text = renderer.read_text(encoding="utf-8")
    if NEW_DISPATCH in text:
        print("BlockRenderer 已经改过，跳过。")
    else:
        if OLD_DISPATCH not in text:
            print("在 BlockRenderer 里没找到 CodeBlock 的渲染处，请人工确认。")
            return 1
        renderer.write_text(text.replace(OLD_DISPATCH, NEW_DISPATCH), encoding="utf-8")
    print("CodeBlock 与 BlockRenderer 已改。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
