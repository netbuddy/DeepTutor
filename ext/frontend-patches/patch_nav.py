#!/usr/bin/env python3
"""在侧栏里加一个「课程」入口。在 ~/DeepTutor-src 下执行。

课程页本身是一个新增文件（不碰上游代码），只有导航条目必须插进上游的侧栏定义里，
所以这里只改这一处，改动越小，升级变基时越好合。
"""

from pathlib import Path

TARGET = Path("web/components/sidebar/SidebarShell.tsx")

ANCHOR = """  {
    href: "/space",
    label: "Learning Space","""

INSERT = """  {
    // 课程：把外部课程取进来，变成可读可练的课本。放在书之后、学习空间之前，
    // 因为它产出的正是书。
    href: "/course",
    label: "Course",
    icon: GraduationCap,
    tooltipKey: "Course tooltip",
  },
  {
    href: "/space",
    label: "Learning Space","""


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if 'href: "/course"' in text:
        print("侧栏里已经有课程入口，跳过。")
        return 0
    if ANCHOR not in text:
        print("在侧栏里没找到插入位置，请人工确认 SidebarShell.tsx 的导航定义。")
        return 1
    text = text.replace(ANCHOR, INSERT, 1)

    # 图标从 lucide 里取，缺哪个补哪个。
    if "GraduationCap" not in text.split("\n\n")[0] and "  GraduationCap," not in text:
        text = text.replace("  LayoutGrid,", "  GraduationCap,\n  LayoutGrid,", 1)
    TARGET.write_text(text, encoding="utf-8")
    print("侧栏已加上课程入口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
