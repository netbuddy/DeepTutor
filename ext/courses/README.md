# 课程

这里放课程原稿和打包好的分发件。

**要自己写一门课，或者修订已有的课，读 [编写指南](编写指南.md)。**
那份文档覆盖从零做一门课的全过程：目录结构、六种内容块的写法、
代码格的运行模型、一章该怎么组织、改完怎么生效、怎么验证、怎么打包分发，
以及一张疑难排查表。

## 目录

| 路径 | 是什么 |
|---|---|
| `编写指南.md` | **写课的人从这里开始** |
| `agent-from-scratch-python/` | 《从零实现一个 AI Agent（Python 版）》讲义原稿 |
| `agent-from-scratch-go/` | 《从零实现一个 AI Agent（Go 版）》讲义原稿 |
| `packages/*.dtcourse` | 打包好的课程，可以直接发给别人导入 |

**原稿是唯一权威**，包是从原稿导出来的产物。改讲义改这里，改完在书的侧栏点
「从原稿重新导入」。

导入时课程会被复制进 `data/user/courses/`——那一份是派生副本，不要直接改。
这一步不能省：执行容器只挂了那一个目录（只读），课程放在别处它看不见，
代码格就跑不起来。

## 最短的三条命令

改完原稿之后重新导入：

```bash
curl -s -X POST http://127.0.0.1:9188/api/v1/ext/course/create \
  -H 'Content-Type: application/json' \
  -d '{"origin": "/home/yun/DeepTutor-ext/courses/agent-from-scratch-python",
       "slug": "agent-from-scratch-python",
       "title": "从零实现一个 AI Agent（Python 版）",
       "replace": true}'
```

逐段真跑一遍验证：

```bash
~/DeepTutor-src/.venv/bin/python ~/DeepTutor-ext/bin/verify-course.py
```

导出成包：

```bash
curl -s -o agent-from-scratch-python.dtcourse \
  http://127.0.0.1:9188/api/v1/ext/course/agent-from-scratch-python/export
```

其余细节全在[编写指南](编写指南.md)里。
