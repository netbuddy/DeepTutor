# opencode 接入

要让 DeepTutor 的三处都用上 opencode：子代理、伙伴、模型供应商。三处情况差别很大。

网页版分析（含配图与实测输出）：<https://claude.ai/code/artifact/a069437c-129f-4bb2-af4a-5cf1d9d18d9e>

| 处 | 状态 | 一句话 |
|---|---|---|
| 子代理 subagent | **已经能用** | 上游 1.5.7 自带 opencode 后端，装 CLI 配模型就行，实测通过 |
| 伙伴 partner | 要写代码 | 机制铺好九成，缺一个引用字段与选择入口，二到三天 |
| 模型供应商 provider | 能做但有硬限制 | 官方没有兼容端点，自己包一层就有，我跑通了；代价是工具调用整条失效 |

---

## 一、子代理：已经内置

`deeptutor/services/subagent/` 下有 `opencode_family.py`（518 行）与 `opencode_server.py`，注册表里 opencode 与它的分支 MiMo Code 都在册，设置里还有 `/settings/agents/opencode` 配置页。

**接法比别的命令行后端更深**：不是逐次调 `run --format json` 拿一段输出，而是拉起 opencode 自己的本地服务、订阅它的事件总线——逐字的文本增量、每一次工具状态变化、需要授权时的询问都能拿到。所以回答是打字机式实时出现的，工具一开始跑就在侧边栏显形。登录凭据完全沿用用户自己的命令行配置，DeepTutor 不经手任何令牌。

### 接入步骤（不需要改代码）

```bash
# 1. 装命令行工具
npm i -g opencode-ai

# 2. 配模型：~/.config/opencode/opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "local-llama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "本地 qwen3.6",
      "options": { "baseURL": "http://192.168.213.116:8084/v1" },
      "models": { "qwen3.6-27B": { "name": "qwen3.6-27B" } }
    }
  },
  "model": "local-llama/qwen3.6-27B"
}
```

3. 在设置里的「已连接的智能体」中连一个 opencode，指定工作目录。

连好之后它会作为一种**特殊类型的知识源**出现在对话的知识库选择器里。在对话里选中它，这一轮就由子代理能力接管：聊天模型只剩 `consult_subagent` 一个工具，它自己决定问什么、看着 opencode 干活、再用自己的话回答学生。每轮能问几次由「最大轮数」限制，同一轮里的多次追问会复用同一个 opencode 会话。

### 实测

```
后端: opencode | 权限模式: bypassPermissions | 沙箱: workspace-write
事件计数: {'text': 23, 'tool': 0, 'other': 0}     ← 23 个逐字文本事件
会话 id: ses_04384a4d2ffe1CVm5WkN
最终答案: list 是可变的（可以增删改元素），tuple 是不可变的（创建后不能修改）。
出错: 无
```

### 内部机制

连接以一条 `type == subagent` 的知识源元数据存在，带着 `agent_kind`（哪种后端）与 `cwd`（工作目录）。`capabilities/subagent/binding.py` 每轮从 `context.knowledge_bases` 里解析出这条引用，`SubagentCapability.is_active` 据此判断要不要接管。

**这一点对第二项很关键**：激活条件只看上下文里的知识源，不看是谁发起的对话。

---

## 二、伙伴：机制铺好九成

伙伴的每个回合走 `PartnerRunner._execute_turn`，它组装一个上下文交给聊天编排器——**和普通对话是同一条路**。所以只要伙伴的上下文里能带上那条子代理引用，现成的能力立刻接管，子代理这一侧一行代码都不用改。

拦住这件事的只有一处：

```python
# services/partners/runtime.py
def _list_kb_names(self) -> list[str]:
    kb_root = get_path_service().get_knowledge_bases_root()
    return KnowledgeBaseManager(base_dir=str(kb_root)).list_knowledge_bases()
```

它列的是伙伴自己工作区里**复制过来的知识库目录**。而子代理连接根本不是一个目录——它是注册表里的一条元数据，复制不过去，于是永远不会出现在伙伴的知识源里。

### 两条路

**方案 A（推荐）**：让伙伴引用一个子代理。

1. `PartnerConfig` 加一个字段记住要用哪个连接（比如 `subagent_ref: str`）；
2. `_build_context` 组装上下文时把它并进 `knowledge_bases` 列表；
3. 伙伴配置界面加一个下拉，选项是已连接的智能体。

后端两处小改，前端一个选择器。权限、预算、会话延续全都沿用现成的。

**方案 B**：给伙伴换一种运行时后端，回合不走聊天编排器，直接交给 opencode 跑完再回。改动大得多，而且要重做一遍伙伴现有的东西——记忆、技能清单、附件、流式投递、备用模型重试。省下的是一层模型调用的延迟。

### 落地前必须想清楚的安全问题

伙伴常常是**对外的**（接在即时通讯渠道上），而 opencode 是能读写文件、能执行命令的编码代理。DeepTutor 给子代理的默认配置是：

```
permission_mode=bypassPermissions
sandbox=workspace-write
auto_approve=true
```

在自己电脑上用没问题，挂到一个陌生人能发消息的渠道上完全是另一回事。

所以方案 A 落地时：那个下拉选择器旁边应当同时显示这条连接的权限摘要，默认收紧到只读；伙伴的工作目录也该限制在它自己的工作区内，而不是任意路径。

---

## 三、模型供应商：官方没有，自己包一层就有

### 事实

起了本机这台 opencode 1.18.10 的服务，拉它自己发布的接口规范逐条查：

```
OpenAPI 3.1.0 | 路由数 162
有 /v1/chat/completions: False
有 /v1/models: False
任何 /v1 开头的路由: 无
```

官方文档也是这么写的：本地服务只提供自己的接口和 ACP，OpenAI 兼容层只存在于它托管的那个服务上。上游有人提过这个需求（issue #31724），还没做。SDK 那边同样——所有交互都走 `session.prompt()`，没有绕过代理循环的原始补全接口。

### 但零件是齐的

162 条路由里做转接需要的都在：

| 路由 | 用途 |
|---|---|
| `POST /session` | 建会话 |
| `POST /session/{id}/message` | 发消息，返回时这一轮就结束了 |
| `GET /event` | 订阅事件总线，逐字增量在 `message.part.delta` |
| `GET /api/model` | 列出它配好的所有模型 |
| `POST /session/{id}/abort` | 中止 |

### 我写了一个转接层，跑通了

`lab/oc_openai_shim.py`（一百六十行）：`GET /v1/models` 映射它的模型清单，`POST /v1/chat/completions` 把一次调用翻译成「建会话 → 发消息 → 收回答」，流式则把事件总线上的增量转写成 OpenAI 的分块。

用标准 OpenAI 客户端直接调：

```
GET /v1/models          25 个模型，含 local-llama/qwen3.6-27B

非流式  8.9s  →  `is` 比较对象身份（内存地址是否相同），`==` 比较对象值（内容是否相等）。
流式    2.3s  →  27 个增量块
```

然后把它当成一条普通的「自定义（OpenAI 接口）」供应商写进 DeepTutor 的模型目录，指定用它跑对话——**DeepTutor 一行代码都没改**：

```json
{"success": true, "data": {
   "response": "递归就是**函数自己调用自己**，通过把一个大问题不断拆成结构相同但规模更小的子问题…",
   "engine": "agent_loop", "rounds": 1, "tool_steps": 0 }}
```

### 硬限制：模型端的工具调用整条失效

注意上面的 `tool_steps: 0`。这不是巧合，是结构性后果。

OpenAI 协议里，工具是「调用方发 `tools` 声明 → 模型回 `tool_calls` → 调用方执行完再发回去」。而 opencode **不按这个协议出牌**：它自带一整套工具，自己决定调什么、自己执行，最后只把一段文本交还。

所以转接层收到工具声明也没处安放只能丢掉，opencode 也永远不会回 `tool_calls`。结果是 DeepTutor 里所有**需要模型主动发起**的工具在这条路上都不会被触发：代码执行、命令执行、联网搜索、咨询子代理，一个都用不了。

有一类仍然有效——由服务端**预先注入上下文**的那部分。用课程知识库实测：

```
工具调用步数: 0
回合数: 1
回答: 根据检索到的内容，**第三章**专门讲解微调。章节标题为：3. 微调一个预训练模型…
```

回答是对的，因为检索结果是服务端塞进上下文的，不依赖模型回报工具调用。这恰好划出了分界线：**能预先准备好的信息照常工作，需要模型临场决定去做的动作全部消失。**

### 转接层还有三处没做

这是可行性验证不是产品实现：

- **会话语义对不齐**：OpenAI 每次带完整历史、无状态；opencode 的会话有状态。现在的做法是每次新建会话、把历史拼成一段提示，语义最接近，代价是丢掉 opencode 自己的上下文复用与缓存。想复用得设计一套会话映射，还要处理过期与并发。
- **没有用量数据**：opencode 不回报 token 数，返回的是零而不是编一个。按用量计费或限流的东西会失灵。
- **权限询问没处理**：opencode 干活时可能停下来要授权，OpenAI 协议里没有对应的表达方式。现在会一直等到超时。产品化要么预先全部放行（危险），要么把询问映射成某种可回答的形式。

### 该不该走这条路

- **只是想让 opencode 答一段话**（比如它接了这边没配的模型）——成立，一百多行就够，DeepTutor 无需改动。
- **想让 opencode 参与教学流程**（查资料、跑代码、看学生的 notebook）——这条路是错的，工具全废，等于把一个能干活的代理降级成只会说话的模型。这件事第一节的子代理已经做到了，而且学生能看见它的实时过程，聊天模型还能追问、能把结果翻译成适合学生的说法。

---

## 建议的推进顺序

| 步骤 | 做什么 | 为什么排在这 |
|---|---|---|
| 1 · 已完成 | 装 opencode、配模型、确认 DeepTutor 能驱动它 | 不用开发就能验证整条链 |
| 2 · 半天 | 在界面里连一个 opencode，在对话里选它当知识源，走一遍真实的教学问答 | 先确认这种交互是不是想要的，再决定要不要往伙伴那边推 |
| 3 · 二到三天 | 做方案 A：伙伴配置加子代理引用，配上权限摘要与只读默认 | 改动集中，风险主要在权限不在代码 |
| 4 · 看需要 | 两边共用一套模型配置：把 opencode 指向 DeepTutor 已配好的模型 | 省掉配两遍，也让子代理和主对话跑在同一个模型上 |
| 5 · 只在特定场景做 | 把转接层产品化（会话映射、用量、权限询问） | 只有确实需要「用 opencode 当纯粹的答话模型」时才值得 |

---

## 这次留在服务器上的

| 东西 | 位置 | 清理方式 |
|---|---|---|
| opencode 1.18.10 | 全局 npm 包 | `npm rm -g opencode-ai` |
| opencode 配置 | `~/.config/opencode/opencode.json` | 直接删 |
| opencode 服务 | 4096，只绑回环 | 杀掉进程 |
| OpenAI 兼容转接层 | 4097，脚本在 `~/DeepTutor-ext/lab/oc_openai_shim.py` | 杀掉进程 |
| 模型目录里的转接层供应商 | `llm-profile-opencode`，原文件备份为 `model_catalog.json.bak` | 从 JSON 里删掉那条 |

**默认使用的模型没有被改动**（仍是 116 上的 qwen3.6-27B）。DeepTutor 的代码本身没有任何改动。
