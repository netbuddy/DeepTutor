#!/usr/bin/env python3
"""把一个课程目录导入成 DeepTutor 里的一本书。

用法：
    <虚拟环境的 python> bin/import-course.py <课程目录> [--language zh] [--book-id ...]

课程目录要能被内核容器看到，也就是必须在 data/user/courses 下面——容器只挂了那一个
目录（只读），放在别处的话页面能显示但代码跑不起来。

重复导入同一个课程是覆盖，不会产生第二本书。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("DEEPTUTOR_HOME", str(Path.home() / "DeepTutor-src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="把课程目录导入成一本书")
    parser.add_argument("course_dir", help="课程根目录，例如 data/user/courses/ml-for-beginners")
    parser.add_argument("--language", default="zh", help="书的语言标记，默认 zh")
    parser.add_argument("--book-id", default="", help="指定书的标识，默认按目录名生成")
    args = parser.parse_args()

    from deeptutor_ext.course import CourseImporter

    importer = CourseImporter(args.course_dir, language=args.language)
    book_id = importer.save(book_id=args.book_id)
    print(f"已导入为书 {book_id}：{importer.stats.describe()}")

    courses_root = (Path(os.environ["DEEPTUTOR_HOME"]) / "data/user/courses").resolve()
    if not str(Path(args.course_dir).expanduser().resolve()).startswith(str(courses_root)):
        print(
            f"提醒：课程不在 {courses_root} 下，内核容器看不到它，页面上的代码将无法运行。",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
