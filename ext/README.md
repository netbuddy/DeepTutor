# DeepTutor 本地扩展

这个目录放我们自己给 DeepTutor 加的功能。它与 DeepTutor 的源码是分开的两棵树，
目的只有一个：**上游发新版时，我们的东西能快速接回去。**

## 文档

本文件是速查；要动手改先读 `docs/`：

| 文档 | 什么时候读 |
|---|---|
| [docs/00-总览.md](docs/00-总览.md) | 第一次接手，或隔了很久回来 |
| [docs/01-部署与运维.md](docs/01-部署与运维.md) | 启停、升级、排故障 |
| [docs/02-扩展接入机制.md](docs/02-扩展接入机制.md) | 加工具／接口，或升级后扩展没生效 |
| [docs/03-notebook执行.md](docs/03-notebook执行.md) | 改代码运行、内核、输出渲染、执行容器 |
| [docs/04-课程模块.md](docs/04-课程模块.md) | 支持新课程排布、改导入、改课程页 |
| [docs/05-踩坑与决策.md](docs/05-踩坑与决策.md) | 遇到怪现象，或想知道某个设计为什么这么选 |
| [docs/06-opencode接入.md](docs/06-opencode接入.md) | 接 opencode 或别的编码代理 |
| [docs/07-实测记录.md](docs/07-实测记录.md) | 引用证据，或复现某次验证 |

## 现在能做什么

侧栏的**课程**页可以把外部课程取进来。填一个 Git 仓库地址（或服务器上的一个目录），
它会摊成三样东西：

| 产出 | 是什么 | 学生在哪儿用 |
|---|---|---|
| 课程目录 | 原始文件，放在 `data/user/courses/<标识>/` | 执行容器只读挂载这一份，跑代码时的工作目录在里面 |
| 一本书 | 章节目录加可运行的页面 | 书籍页里读和练 |
| 一个检索索引 | 全课正文的知识库，自动绑在书上 | 书页对话面板据此翻遍整门课回答问题 |

书页里的每段代码都能**当场运行**：代码可改，输出（文字、pandas 表格、图表、报错回溯）
就地显示，点「问助教」会把这一格的代码和运行结果一起带进对话面板。

代码跑在一个独立容器里的长驻内核上：同一页共用一个内核，所以靠前的格子定义的变量
靠后的格子能直接用。学生跳着运行会撞上「变量没定义」，所以每格都有一个
「从头跑到这」，会先把前面的格子依次补跑一遍。

认得两种课程排布，加一种只要在 `deeptutor_ext/course/layouts.py` 里加一个识别函数：

* **讲义配 notebook**：一层模块目录，每课一个子目录，里面是 README 加一份 `.ipynb`
  （microsoft/ML-For-Beginners 是这一类）；
* **目录树配正文**：一份 `_toctree.yml` 驱动一堆 `.mdx`，代码写在围栏里
  （huggingface 的课程是这一类）。

命令行也能导（页面做的是同一件事）：

```bash
cd ~/DeepTutor-ext
curl -X POST -H 'Content-Type: application/json' \
  -d '{"origin":"https://github.com/huggingface/course.git","language":"zh","build_index":true}' \
  http://127.0.0.1:9188/api/v1/ext/course/create
```

重复导入同一门课是覆盖，不会多出一本书。外部课程里读不了的文件（Git LFS 指针、
空文件、坏编码）会被跳过并计数，不会让整门课导入失败。

## 两个目录的分工

| 目录 | 是什么 | 归谁改 |
|---|---|---|
| `~/DeepTutor-src` | DeepTutor 官方源码，一个 git 工作树，当前停在 v1.5.7 | 原则上不改。确实必须改的，提交在 `local` 分支上 |
| `~/DeepTutor-ext` | 我们的扩展包、启停脚本、自检脚本、文档 | 我们自己的地盘，升级完全不影响它 |

两者共用 `~/DeepTutor-src/.venv` 这一个虚拟环境。

## 扩展是怎么挂上去的

DeepTutor 没有给工具留插件入口（源码里那个 `deeptutor.plugins.loader` 的钩子从未实现），
所以我们自己造了一条不碰宿主源码的通路，一共三步：

1. `deeptutor_ext` 作为一个独立的 Python 包，装进 DeepTutor 用的虚拟环境。
2. 虚拟环境的 `site-packages` 下放一个 `deeptutor_ext.pth` 文件。Python 启动时会执行
   `.pth` 里以 `import` 开头的行，于是每一个用到这个环境的进程——`deeptutor` 命令、
   后端的 uvicorn、后台任务——都会自动加载扩展，不必改任何启动方式。
3. 那一行导入的模块只做一件事：登记一个「等 `deeptutor.tools.builtin` 加载完再动手」的
   回调。等宿主那个模块加载完成的瞬间，我们把自己的工具类追加进它的内置工具清单，
   宿主的工具注册表随后读到的就是加好的版本。

结果是 **DeepTutor 的源码一个字符都没改**，升级时不产生任何冲突。代价是接入依赖三个
宿主符号（`BUILTIN_TOOL_TYPES`、`BUILTIN_TOOL_NAMES`、`CONFIGURABLE_BUILTIN_TOOL_NAMES`），
上游要是改了名字，接入会**静默失效**——工具只是不出现，界面上看不出异常。
`make verify` 就是为了在升级后立刻发现这件事。

## 日常命令

```bash
cd ~/DeepTutor-ext

make install         # 首次安装扩展包与站点钩子
make kernel-start    # 启动学生代码的执行容器（必须先起，否则页面上跑不了代码）
make start           # 启动 DeepTutor（前端 9187，后端 9188）
make stop
make restart
make status          # 版本、进程、端口
make health          # 前后端各请求一次
make verify          # 接入自检，升级后必跑
make kernel-status   # 执行容器的状态与活跃内核数
make logs            # 跟踪日志
```

冒烟测试内核那一侧（跨格状态、图片落盘与公开地址、表格、报错、重置）：

```bash
~/DeepTutor-src/.venv/bin/python bin/smoke-kernel.py
```

执行容器的镜像是我们自己构建的（`kernel-image/Dockerfile`）：官方科学计算镜像之外
还带 transformers、torch 的 CPU 版、datasets，因为 Hugging Face 的课程从第一章就要用。
第一次构建要下载一两 GB：

```bash
make kernel-build && make kernel-stop && make kernel-start
```

没构建过也能跑——启动脚本会退回官方科学计算镜像，课程里纯 pandas/sklearn 的部分照样能用。

`make verify` 检查五件事：站点钩子在不在、宿主的三个符号还在不在、扩展工具有没有真的
进注册表、该自动挂载的有没有登记、沙箱能不能真的执行命令。

最后一项是单独实现的，没有用 DeepTutor 自带的健康探针——上游那个探针只看返回结构里的
`error` 字段，而 bubblewrap 失败时是「进程正常退出、退出码非零、错误在标准错误里」，
`error` 是空的，探针会误报健康。我们的检查改为真跑一条 `echo` 看退出码和输出。

## 升级流程

```bash
cd ~/DeepTutor-ext
make upgrade VERSION=v1.5.8
```

它按顺序做七件事：停服务 → 从上游取新标签 → 把本地源码改动变基到新版本 →
重装后端依赖 → 重装前端依赖 → 重新安装扩展并跑自检 → 启动。

只有第三步可能需要人工介入。本地源码改动目前有三笔，都在 `~/DeepTutor-src` 的 `local` 分支上，`upstream-base`
这个本地标签记录它们基于哪个上游版本：

1. 书页里的代码块按 payload 分派到可运行组件（新增 `RunnableCell.tsx`，改
   `CodeBlock.tsx` 与 `BlockRenderer.tsx`）；
2. 单元格的「问助教」接进书页对话面板（改 `page.tsx` 与 `BookChatPanel.tsx`）；
3. 网页端默认界面语言改成中文（改 `app-shell-storage.ts`）——DeepTutor 的回答语言
   跟着界面语言走，上游默认会让每个新浏览器落到英文；
4. 课程模块的前端（新增 `app/(workspace)/course/page.tsx`，改 `SidebarShell.tsx`
   加导航入口，两份 `locales/*/app.json` 各补两条文案）。

合计十个文件、八百来行，其中六百多行是新增的独立文件，真正嵌进上游代码的只有
六处小改动。升级时 `git rebase --onto <新版本> upstream-base local`，冲突时 make
会停下来并打印接下来该敲什么。`frontend-patches/` 下留着生成这些改动的脚本，
上游把某处改得对不上时，改脚本比手工重做更省事。

`make patches` 把 `local` 分支上的提交导出成补丁文件放进 `patches/`，便于审阅与备份——
变基之后提交哈希会变，有一份补丁在手更踏实。

## 端口

这台机器上的端口分配比较拥挤，选端口前务必先看 `ss -tln`：

| 端口 | 归谁 |
|---|---|
| 9181 / 9182 / 9183 | pip 安装的那套 DeepTutor（前端／后端／使用手册），仍在运行 |
| 9184 | 可行性验证时起的 Jupyter 容器，只绑本机回环 |
| 9185 | novnc 的 websockify，**不是我们的，别占** |
| 9187 / 9188 | 源码版 DeepTutor（前端／后端） |
| 9189 | 学生代码的执行容器，只绑本机回环，局域网访问不到 |

改端口要同时改 `~/DeepTutor-src/data/user/settings/system.json`。DeepTutor 启动时会
自己检测端口冲突并明确报错退出，不会默默漂移到别的端口。

## 与 pip 版的关系

`~/DeepTutor` 那套 pip 安装的 1.5.6 仍在 9181 上运行，两套并存，各自有独立的
`data` 目录。源码版的模型配置是从 pip 版复制过来的，知识库和会话记录没有共享。
等源码版验收通过、功能补齐之后，再决定是把 pip 版停掉，还是让它继续作为稳定版留着。
