# DeepTutor 本地扩展

这个目录放我们自己给 DeepTutor 加的功能。它与 DeepTutor 的源码是分开的两棵树，
目的只有一个：**上游发新版时，我们的东西能快速接回去。**

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

make install    # 首次安装扩展包与站点钩子
make start      # 启动（前端 9187，后端 9188）
make stop
make restart
make status     # 版本、进程、端口
make health     # 前后端各请求一次
make verify     # 接入自检，升级后必跑
make logs       # 跟踪日志
```

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

只有第三步可能需要人工介入。当前没有任何本地源码改动，这一步会退化成简单的切换标签；
将来如果为了做 notebook 界面而必须改前端，改动会提交在 `~/DeepTutor-src` 的 `local`
分支上，`upstream-base` 这个本地标签记录它基于哪个上游版本，升级时用
`git rebase --onto <新版本> upstream-base local` 变基。冲突时 make 会停下来并打印
接下来该敲什么。

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

改端口要同时改 `~/DeepTutor-src/data/user/settings/system.json`。DeepTutor 启动时会
自己检测端口冲突并明确报错退出，不会默默漂移到别的端口。

## 与 pip 版的关系

`~/DeepTutor` 那套 pip 安装的 1.5.6 仍在 9181 上运行，两套并存，各自有独立的
`data` 目录。源码版的模型配置是从 pip 版复制过来的，知识库和会话记录没有共享。
等源码版验收通过、功能补齐之后，再决定是把 pip 版停掉，还是让它继续作为稳定版留着。
