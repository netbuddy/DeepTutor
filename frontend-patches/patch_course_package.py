#!/usr/bin/env python3
"""给课程页加上「导出为包」与「从课程包导入」。在 ~/DeepTutor-src 下执行。

课程页本身是我们新增的文件，改动不影响上游代码，但仍然写成可重复执行的脚本——
上游升级后要重放这些改动时，跑脚本比手工重做省事。
"""

from pathlib import Path

TARGET = Path("web/app/(workspace)/course/page.tsx")

ICONS_OLD = """import {
  AlertCircle,
  BookOpen,
  Database,
  Download,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";"""

ICONS_NEW = """import {
  AlertCircle,
  BookOpen,
  Database,
  Download,
  Loader2,
  Package,
  Plus,
  Trash2,
  Upload,
} from "lucide-react";"""

STATE_OLD = "  const [creating, setCreating] = useState(false);"
STATE_NEW = """  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);"""

ACTIONS_ANCHOR = "  async function removeCourse(course: CourseRecord) {"
ACTIONS_NEW = '''  function exportCourse(course: CourseRecord) {
    // 直接让浏览器去下载：包可能有几十 MB，走 fetch 再转 blob 会先整个塞进内存。
    setNotice(`正在打包《${course.title}》，包较大时要等一会儿…`);
    window.location.href = apiUrl(`/api/v1/ext/course/${course.slug}/export`);
  }

  async function importPackage(file: File) {
    setImporting(true);
    setFailure("");
    setNotice(`正在导入课程包 ${file.name}…`);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("replace", String(replace));
      const response = await fetch(apiUrl("/api/v1/ext/course/import-package"), {
        method: "POST",
        body: form,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setFailure(data?.detail || `导入失败（HTTP ${response.status}）`);
        setNotice("");
        return;
      }
      const stats = data.course?.stats || {};
      setNotice(
        `已导入《${data.course?.title}》：${stats.chapters || 0} 章、${stats.pages || 0} 页。` +
          "检索索引需要你自己点一次「建检索索引」——包里不含索引。",
      );
      await load();
    } catch (error) {
      setFailure(
        `导入失败：${error instanceof Error ? error.message : String(error)}`,
      );
      setNotice("");
    } finally {
      setImporting(false);
    }
  }

  async function removeCourse(course: CourseRecord) {'''

SUBMIT_OLD = """          <div>
            <button
              type="button"
              onClick={() => void createCourse()}
              disabled={creating}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-60"
            >
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              取课程
            </button>
          </div>"""

SUBMIT_NEW = """          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void createCourse()}
              disabled={creating}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-60"
            >
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              取课程
            </button>

            <span className="text-xs text-[var(--muted-foreground)]">或者</span>

            <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--border)] px-4 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--muted)]">
              {importing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              从课程包导入
              <input
                type="file"
                accept=".dtcourse,.tar.gz,application/gzip"
                className="hidden"
                disabled={importing}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void importPackage(file);
                }}
              />
            </label>
          </div>
          <p className="text-xs text-[var(--muted-foreground)]">
            课程包是别人打包好的一门课（<code>.dtcourse</code> 文件）。
            包里只有课程原文，课本会在这台机器上重新生成。
          </p>"""

CARD_ANCHOR = """                <button
                  type="button"
                  onClick={() => void removeCourse(course)}"""

CARD_NEW = """                <button
                  type="button"
                  onClick={() => exportCourse(course)}
                  title="打成一个包，可以拷给别人导入"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                >
                  <Package className="h-3.5 w-3.5" />
                  导出为包
                </button>
                <button
                  type="button"
                  onClick={() => void removeCourse(course)}"""

PAIRS = [
    (ICONS_OLD, ICONS_NEW),
    (STATE_OLD, STATE_NEW),
    (ACTIONS_ANCHOR, ACTIONS_NEW),
    (SUBMIT_OLD, SUBMIT_NEW),
    (CARD_ANCHOR, CARD_NEW),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    for old, new in PAIRS:
        if new in text:
            continue
        if old not in text:
            print("没找到要替换的片段，请人工确认：")
            print(old.splitlines()[0][:70])
            return 1
        text = text.replace(old, new, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("课程页已加上导出为包与从课程包导入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
