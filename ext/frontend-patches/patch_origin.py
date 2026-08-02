#!/usr/bin/env python3
"""让书记住「课程原稿在哪」，而不只是「内部副本在哪」。在 ~/DeepTutor-ext 下执行。

导入课程时，来源目录会被复制进 data/user/courses（因为内核容器只挂了那一个目录，
放在别处它看不见，代码格就跑不起来）。之前书的 metadata 里只记了副本的位置，
于是「从原稿重新导入」按钮读的是副本——改了真正的原稿也不会生效。

这里补一个 course_origin，记住你当初传进来的那个来源。
"""

from pathlib import Path

IMPORTER = Path("deeptutor_ext/course/importer.py")
SERVICE = Path("deeptutor_ext/course/service.py")

INIT_OLD = '''    def __init__(self, course_root: str | Path, *, title: str = "", language: str = "zh") -> None:
        self.root = Path(course_root).expanduser().resolve()'''
INIT_NEW = '''    def __init__(
        self,
        course_root: str | Path,
        *,
        title: str = "",
        language: str = "zh",
        origin: str = "",
    ) -> None:
        # course_root 是内核容器看得见的那份副本；origin 是你当初传进来的来源
        # （可能是 Git 地址，也可能是本机上另一个目录）。两个都要记，
        # 因为「重新导入」要读的是后者。
        self.origin = origin
        self.root = Path(course_root).expanduser().resolve()'''

META_OLD = '''                "origin": "course_import",
                "course_slug": slug,
                "course_root": str(self.root),'''
META_NEW = '''                "origin": "course_import",
                "course_slug": slug,
                "course_root": str(self.root),
                "course_origin": self.origin or str(self.root),'''

SERVICE_OLD = "        importer = CourseImporter(fetched.path, title=title, language=language)"
SERVICE_NEW = (
    "        importer = CourseImporter(\n"
    "            fetched.path, title=title, language=language, origin=fetched.origin\n"
    "        )"
)


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
    if not patch(IMPORTER, [(INIT_OLD, INIT_NEW), (META_OLD, META_NEW)]):
        return 1
    if not patch(SERVICE, [(SERVICE_OLD, SERVICE_NEW)]):
        return 1
    print("书现在记得课程原稿的位置了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
