# 课程

这里放 DeepTutor 扩展自带的课程原稿，以及打包好的分发件。

## 目录

| 路径 | 是什么 |
|---|---|
| `agent-from-scratch-python/` | 《从零实现一个 AI Agent（Python 版）》讲义原稿 |
| `agent-from-scratch-go/` | 《从零实现一个 AI Agent（Go 版）》讲义原稿 |
| `packages/*.dtcourse` | 打包好的课程，可以直接发给别人导入 |

原稿是权威来源，包是从原稿导出来的产物。改讲义改原稿，改完重新导入再重新导出。

## 讲义结构

一门课就是一个目录：

    <课程名>/
      README.md                     课本首页
      chapters/zh/_toctree.yml      目录：分几个部分、每部分几章、每章标题
      chapters/zh/part1/1.md        一章一个文件

`_toctree.yml` 里的 `local` 字段是相对 `chapters/zh/` 的路径，不带 `.md` 后缀。

讲义里的每个代码围栏都会变成课本上一个可运行的代码格。Python 用围栏标记
` ```python `，Go 用 ` ```go `。不带语言标记的围栏只显示，不可运行。

**Go 讲义有一条额外约束**：Go 没有长驻内核，运行方式是累积编译——
同一页里前面格子写下的文件会保留，运行某一格等于把到这一格为止的文件一起编译。
每格开头的 `// file: xxx.go` 决定写进哪个文件，同名会覆盖。所以：

- 跨格子要用的常量和函数**不要写在 `main.go` 里**，后面每一格都有自己的 `main`。
- 每一格都必须能**独立编译**，不能引用后面格子才定义的东西。

## 改完之后怎么重新导入

课程原稿要放在服务器上一个 DeepTutor 能读到的位置（下面用 `~/agent-course/`）：

    rsync -a --delete courses/agent-from-scratch-python/ ~/agent-course/python/

    curl -s -X POST http://127.0.0.1:9188/api/v1/ext/course/create \
      -H 'Content-Type: application/json' \
      -d '{"origin":"/home/yun/agent-course/python",
           "slug":"agent-from-scratch-python",
           "title":"从零实现一个 AI Agent（Python 版）",
           "replace":true}'

`replace:true` 是覆盖同名课程，不会产生第二本书。

## 逐段真跑一遍

导入之后一定要跑一遍验证，它会把每一页的每个代码格真的执行一次：

    ~/DeepTutor-src/.venv/bin/python ~/DeepTutor-ext/bin/verify-course.py

两门课加起来 299 段代码，跑完要十几分钟（第 20 章的每个用例都要真调模型）。
Go 的编译错误会写到 stderr 而不体现在内核状态里，验证脚本对此有专门的判断。

## 导出成包

    curl -s -o agent-from-scratch-python.dtcourse \
      http://127.0.0.1:9188/api/v1/ext/course/agent-from-scratch-python/export

包是一个 gzip 压缩的 tar，里面只有 `package.json`、`README.md` 和 `course/` 原稿——
**不含课本和检索索引**，因为那两样带着本机的绝对路径，换台机器就不对了。
导入时会在本机重新生成。

## 导入别人给的包

在设置里的课程页面上传，或者：

    curl -s -X POST http://127.0.0.1:9188/api/v1/ext/course/import-package \
      -F 'file=@agent-from-scratch-python.dtcourse' \
      -F 'slug=agent-from-scratch-python' \
      -F 'replace=true'

不传 `slug` 就沿用包里原来的名字。
