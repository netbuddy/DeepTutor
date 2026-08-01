"use client";

/**
 * 课程管理页：把外部课程取进来，变成可读、可练、可检索的一门课。
 *
 * 一门课导入后会摊成三样东西——课程原始文件、一本可运行的书、一个可选的检索索引。
 * 这一页把这三样的状态摆在一起，并给出对应的动作：打开课本去学、建索引让助教能翻遍
 * 全课回答、不要了就整套删掉。
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  BookOpen,
  Database,
  Download,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { apiUrl } from "@/lib/api";

interface CourseStats {
  chapters?: number;
  pages?: number;
  text_blocks?: number;
  code_blocks?: number;
  runnable_cells?: number;
}

interface CourseRecord {
  slug: string;
  title: string;
  origin: string;
  kind: string;
  layout: string;
  language: string;
  book_id: string;
  kb_name: string;
  size_mb: number;
  stats: CourseStats;
  imported_at: number;
  indexed_at: number;
}

const LAYOUT_LABEL: Record<string, string> = {
  notebook: "讲义配 notebook",
  toctree: "目录树配正文",
};

function formatTime(seconds: number): string {
  if (!seconds) return "—";
  return new Date(seconds * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CoursePage() {
  const router = useRouter();
  const [courses, setCourses] = useState<CourseRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [busySlug, setBusySlug] = useState("");

  const [origin, setOrigin] = useState("");
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("zh");
  const [buildIndex, setBuildIndex] = useState(true);
  const [replace, setReplace] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/v1/ext/course/list"));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setCourses(data.courses || []);
      setFailure("");
    } catch (error) {
      setFailure(
        `取课程列表失败：${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createCourse() {
    if (!origin.trim()) {
      setFailure("请先填课程来源：一个 Git 仓库地址，或服务器上的一个目录。");
      return;
    }
    setCreating(true);
    setFailure("");
    setNotice(
      buildIndex
        ? "正在取课程并建检索索引，全课正文都要过一遍向量化，可能要几分钟…"
        : "正在取课程…",
    );
    try {
      const response = await fetch(apiUrl("/api/v1/ext/course/create"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin: origin.trim(),
          title: title.trim(),
          language,
          replace,
          build_index: buildIndex,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setFailure(data?.detail || `导入失败（HTTP ${response.status}）`);
        setNotice("");
        return;
      }
      const stats = data.course?.stats || {};
      setNotice(
        data.index_error
          ? data.index_error
          : `已导入《${data.course?.title}》：${stats.chapters || 0} 章、${stats.pages || 0} 页，可运行的代码段 ${stats.runnable_cells || 0} 个。`,
      );
      setOrigin("");
      setTitle("");
      await load();
    } catch (error) {
      setFailure(
        `导入失败：${error instanceof Error ? error.message : String(error)}`,
      );
      setNotice("");
    } finally {
      setCreating(false);
    }
  }

  async function rebuildIndex(slug: string) {
    setBusySlug(slug);
    setFailure("");
    setNotice("正在建检索索引，全课正文都要过一遍向量化，可能要几分钟…");
    try {
      const response = await fetch(apiUrl(`/api/v1/ext/course/${slug}/index`), {
        method: "POST",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setFailure(data?.detail || `建索引失败（HTTP ${response.status}）`);
        setNotice("");
        return;
      }
      setNotice(`检索索引已就绪：${data.kb_name}`);
      await load();
    } catch (error) {
      setFailure(
        `建索引失败：${error instanceof Error ? error.message : String(error)}`,
      );
      setNotice("");
    } finally {
      setBusySlug("");
    }
  }

  async function removeCourse(course: CourseRecord) {
    const confirmed = window.confirm(
      `确定要删除《${course.title}》吗？课程文件、对应的课本和检索索引会一起删掉。`,
    );
    if (!confirmed) return;
    setBusySlug(course.slug);
    try {
      await fetch(apiUrl(`/api/v1/ext/course/${course.slug}/delete`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ drop_book: true, drop_kb: true }),
      });
      setNotice(`已删除《${course.title}》。`);
      await load();
    } catch (error) {
      setFailure(
        `删除失败：${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setBusySlug("");
    }
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-5xl flex-col gap-6 overflow-y-auto px-6 py-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-[var(--foreground)]">课程</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          把外部课程取进来：讲义变成可读的课本，notebook
          和代码段变成能当场运行的练习，全课正文还能建成检索索引，让助教翻遍整门课回答问题。
        </p>
      </header>

      <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
          <Plus className="h-4 w-4" />
          新增课程
        </div>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--muted-foreground)]">
              课程来源：一个 Git 仓库地址，或服务器上的一个目录
            </span>
            <input
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              placeholder="https://github.com/huggingface/course.git"
              className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]"
            />
          </label>
          <div className="flex flex-wrap gap-3">
            <label className="flex flex-1 flex-col gap-1">
              <span className="text-xs text-[var(--muted-foreground)]">
                课程名称（留空就用课程里写的标题）
              </span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：Hugging Face LLM 课程"
                className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]"
              />
            </label>
            <label className="flex w-40 flex-col gap-1">
              <span className="text-xs text-[var(--muted-foreground)]">
                优先用哪种语言的正文
              </span>
              <select
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
                className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]"
              >
                <option value="zh">中文</option>
                <option value="en">英文</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={buildIndex}
                onChange={(event) => setBuildIndex(event.target.checked)}
              />
              <span>顺带建检索索引（慢，但学起来助教能引用到具体哪一课）</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={replace}
                onChange={(event) => setReplace(event.target.checked)}
              />
              <span>已存在同名课程时覆盖</span>
            </label>
          </div>
          <div>
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
          </div>
        </div>
      </section>

      {notice && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2 text-sm text-[var(--foreground)]">
          {notice}
        </div>
      )}
      {failure && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-sm text-red-600 dark:text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{failure}</span>
        </div>
      )}

      <section className="flex flex-col gap-3">
        <div className="text-sm font-medium text-[var(--foreground)]">
          已有课程{loading ? "" : `（${courses.length}）`}
        </div>
        {loading && (
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在读取…
          </div>
        )}
        {!loading && courses.length === 0 && (
          <div className="rounded-2xl border border-dashed border-[var(--border)] px-4 py-8 text-center text-sm text-[var(--muted-foreground)]">
            还没有课程。上面填一个 Git 仓库地址就能取一门进来。
          </div>
        )}
        {courses.map((course) => (
          <article
            key={course.slug}
            className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-base font-medium text-[var(--foreground)]">
                    {course.title}
                  </h2>
                  <span className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                    {LAYOUT_LABEL[course.layout] || course.layout || "未知排布"}
                  </span>
                </div>
                <p className="mt-1 truncate text-xs text-[var(--muted-foreground)]">
                  {course.origin}
                </p>
                <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-[var(--muted-foreground)]">
                  <div>
                    <dt className="inline">章节 </dt>
                    <dd className="inline text-[var(--foreground)]">
                      {course.stats?.chapters ?? 0} 章 {course.stats?.pages ?? 0} 页
                    </dd>
                  </div>
                  <div>
                    <dt className="inline">可运行代码段 </dt>
                    <dd className="inline text-[var(--foreground)]">
                      {course.stats?.runnable_cells ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline">占用 </dt>
                    <dd className="inline text-[var(--foreground)]">
                      {course.size_mb} MB
                    </dd>
                  </div>
                  <div>
                    <dt className="inline">导入于 </dt>
                    <dd className="inline text-[var(--foreground)]">
                      {formatTime(course.imported_at)}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline">检索索引 </dt>
                    <dd className="inline text-[var(--foreground)]">
                      {course.kb_name
                        ? `${course.kb_name}（${formatTime(course.indexed_at)}）`
                        : "未建"}
                    </dd>
                  </div>
                </dl>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => router.push(`/book?book=${course.book_id}`)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--foreground)] hover:bg-[var(--muted)]"
                >
                  <BookOpen className="h-3.5 w-3.5" />
                  打开课本
                </button>
                <button
                  type="button"
                  onClick={() => void rebuildIndex(course.slug)}
                  disabled={busySlug === course.slug}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
                >
                  {busySlug === course.slug ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Database className="h-3.5 w-3.5" />
                  )}
                  {course.kb_name ? "重建索引" : "建检索索引"}
                </button>
                <button
                  type="button"
                  onClick={() => void removeCourse(course)}
                  disabled={busySlug === course.slug}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-red-600 hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  删除
                </button>
              </div>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
