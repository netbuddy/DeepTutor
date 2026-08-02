#!/usr/bin/env python3
"""课程书上的「重建书籍」改成「从原稿重新导入」。在 ~/DeepTutor-src 下执行。

上游的「重建书籍」会**删掉这本书的全部页面**，再让书引擎按大纲用模型重新生成
每一页。对 DeepTutor 自己生成的书这是对的——那些页本来就是模型写的。
但对导入的课程，页面是人写的讲义，一点就全没了，而确认框的措辞
（"Existing generated pages will be replaced"）看不出这个区别。

导入的课程在书的 metadata 里带着 origin=course_import、course_slug、course_root。
认出这类书之后：

* 按钮文字改成「从原稿重新导入」；
* 确认框说清楚它会从哪个目录重新读；
* 点下去调课程模块的导入接口（等价于命令行那条 curl），而不是走书引擎的重建。

这样这个按钮对课程反而有用了：改完讲义在页面上点一下就生效，不用去命令行。
"""

from pathlib import Path

BOOK = Path("web/app/(workspace)/book")
PAGE = BOOK / "page.tsx"
SIDEBAR = BOOK / "components/BookSidebar.tsx"

# ── page.tsx：分流到课程导入 ─────────────────────────────────────────

HANDLER_OLD = """    if (!detail) return;
    if (
      !confirm(
        t(
          "Rebuild this book using the current chapter structure? Existing generated pages will be replaced.",
        ),
      )
    ) {
      return;
    }
    setRebuildingBook(true);
    try {
      await bookApi.rebuild(detail.book.id, true);"""

HANDLER_NEW = """    if (!detail) return;

    // 导入的课程走另一条路。上游的「重建」会删光全部页面再让模型重新生成，
    // 而课程的页面是人写的讲义——那样点一下就全没了。对课程来说，
    // 「重建」应该是从课程原稿重新读一遍。
    const meta = (detail.book.metadata || {}) as Record<string, unknown>;
    const courseSlug = String(meta.course_slug || "");
    const courseRoot = String(meta.course_root || "");
    if (meta.origin === "course_import" && courseSlug && courseRoot) {
      if (
        !confirm(
          `从课程原稿重新导入这本书？\\n\\n原稿目录：${courseRoot}\\n\\n` +
            `页面内容会按原稿刷新，模型不会改写任何内容。`,
        )
      ) {
        return;
      }
      setRebuildingBook(true);
      try {
        const response = await fetch("/api/v1/ext/course/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            origin: courseRoot,
            slug: courseSlug,
            title: detail.book.title,
            replace: true,
          }),
        });
        if (!response.ok) {
          const detailText = await response.text();
          alert(`重新导入失败：${detailText.slice(0, 300)}`);
          return;
        }
        const refreshed = await loadBookDetail(detail.book.id);
        setSelectedPageId(refreshed.pages[0]?.id || null);
        setView("reader");
        await refreshBooks();
      } finally {
        setRebuildingBook(false);
      }
      return;
    }

    if (
      !confirm(
        t(
          "Rebuild this book using the current chapter structure? Existing generated pages will be replaced.",
        ),
      )
    ) {
      return;
    }
    setRebuildingBook(true);
    try {
      await bookApi.rebuild(detail.book.id, true);"""

SIDEBAR_PROP_OLD = """  onRebuild?: () => void;
  rebuilding?: boolean;
}"""
SIDEBAR_PROP_NEW = """  onRebuild?: () => void;
  rebuilding?: boolean;
}

/** 这本书是不是从课程目录导入的。是的话「重建」的含义不同，见 page.tsx。 */
function isImportedCourse(book: Book | null): boolean {
  const meta = (book?.metadata || {}) as Record<string, unknown>;
  return meta.origin === "course_import" && Boolean(meta.course_slug);
}"""

SIDEBAR_LABEL_OLD = """          {t("Rebuild book")}
        </button>"""
SIDEBAR_LABEL_NEW = """          {isImportedCourse(book) ? "从原稿重新导入" : t("Rebuild book")}
        </button>"""

SIDEBAR_TITLE_OLD = """          onClick={onRebuild}
          disabled={rebuilding}"""
SIDEBAR_TITLE_NEW = """          onClick={onRebuild}
          disabled={rebuilding}
          title={
            isImportedCourse(book)
              ? "按课程原稿重新读一遍，页面内容会刷新，模型不会改写任何内容"
              : "删除现有页面，让模型按大纲重新生成"
          }"""


def patch(path: Path, pairs) -> bool:
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in text:
            continue
        if old not in text:
            print(f"{path.name} 里没找到片段：{old[:70]}…")
            return False
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    if not patch(PAGE, [(HANDLER_OLD, HANDLER_NEW)]):
        return 1
    if not patch(
        SIDEBAR,
        [
            (SIDEBAR_PROP_OLD, SIDEBAR_PROP_NEW),
            (SIDEBAR_TITLE_OLD, SIDEBAR_TITLE_NEW),
            (SIDEBAR_LABEL_OLD, SIDEBAR_LABEL_NEW),
        ],
    ):
        return 1
    print("课程书上的「重建书籍」已改成「从原稿重新导入」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
