#!/usr/bin/env python3
"""把网页端的默认界面语言从英文改成中文。在 ~/DeepTutor-src 下执行。

DeepTutor 的回答语言跟着界面语言走，而界面语言存在每个浏览器自己的本地存储里，
服务端没有全局开关。上游的归一函数写成「取到的值是 zh 才用中文，其余一律英文」，
于是任何没手工切过语言的浏览器第一次打开都是英文界面、英文回答。这里把判断反过来：
显式选了英文才用英文，其余一律中文。手工选英文的人不受影响。

pip 安装的那套是靠改编译产物做到这一点的；源码部署跑的是这份源文件，所以改在这里。
"""

from pathlib import Path

TARGET = Path("web/context/app-shell-storage.ts")

REPLACEMENTS = [
    (
        '  return value === "zh" ? "zh" : "en";\n}',
        "  // 默认中文：只有显式选了英文才用英文。上游默认是反过来的，\n"
        "  // 那会让每个新浏览器都以英文界面打开，而回答语言跟着界面语言走。\n"
        '  return value === "en" ? "en" : "zh";\n}',
    ),
    (
        'export function readStoredLanguage(): AppLanguage {\n'
        '  if (typeof window === "undefined") return "en";',
        'export function readStoredLanguage(): AppLanguage {\n'
        '  if (typeof window === "undefined") return "zh";',
    ),
    (
        "    return normalizeLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY));\n"
        "  } catch {\n"
        '    return "en";\n'
        "  }",
        "    return normalizeLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY));\n"
        "  } catch {\n"
        '    return "zh";\n'
        "  }",
    ),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    changed = 0
    for old, new in REPLACEMENTS:
        if new in text:
            continue
        if old not in text:
            print("没找到要替换的片段，上游可能改了写法，请重新查一遍：")
            print(old.splitlines()[0])
            return 1
        text = text.replace(old, new, 1)
        changed += 1
    if changed:
        TARGET.write_text(text, encoding="utf-8")
        print(f"默认界面语言已改成中文（改了 {changed} 处）。")
    else:
        print("默认界面语言已经是中文，无需重复修改。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
