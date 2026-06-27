# LangGraph-Algo-System 系统内核 v2.1

> 基于 LangGraph 的认知功能拓扑化 Agent 系统 — 架构契约、拓扑、节点主权定义。

---

## 一、宪法 (顶层约束)

| 条款 | 概要 |
|------|------|
| §0 绝对命令 | 任何重构前需理解当前拓扑；严禁擅自修改图路由和节点主权边界 |
| §1 状态隔离 | `AgentState` 是唯一信息载体；节点间禁止 direct import 调用，禁止共享变量 |
| §2 节点主权 | 每个节点只读写自己主权的字段，不越界写入其他节点的字段 |
| §3 爆炸半径 | LLM 解析必须 `try-except`；异常写 Fallback String，不崩 Graph |
| §4 纯粹性 | 节点不知道边界外的事存在。Gatekeeper 不知道 executor 长什么样 |

---

## 二、拓扑 (graph.py)

```
START
  │
  ▼
extractor          — 前台提取（正则+LLM 互补）
  │
  ▼
summarizer         — 背景生成（纯字符串拼接 fact_ledger）
  │
  ▼
fetcher            — 题号查找（本地 slug_map → doocs → GraphQL → 降级）
  │
  ▼
diagnosis          — 意图分类（XML <intent>/<reason>/<sufficiency> 标签）
  │
  ├── sufficiency > 0.8 ───────────────── rag → (intent 路由)  [Flash 快路径]
  │
  └── sufficiency ≤ 0.8 → gatekeeper
           ├── ask → mirror → END
           └── proceed → rag → (intent 路由)
                   ├─ error    → reviewer ──┐
                   ├─ teach    → tutor    ──┤──→ format → mirror → END
                   └─ generate → generator ──┘
```

**节点总数**: 11 (extractor, summarizer, fetcher, diagnosis, gatekeeper, rag, reviewer, tutor, generator, format, mirror)

**条件路由**: 3 条
1. `diagnosis` → `_route_after_diagnosis`：sufficiency > 0.8 走 Flash 快路径，否则走 gatekeeper
2. `gatekeeper` → `_route_after_gatekeeper`：ask → mirror，proceed → rag
3. `rag` → `_route_after_rag`：按 intent 分流到 reviewer / tutor / generator

---

## 三、数据载体 (state.py → AgentState)

### 字段定义

```python
class AgentState(TypedDict):
    # ── LangGraph 管理 ──
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # ── Extractor 写入：从用户输入提取 ──
    target_id: str               # 题号
    source_code: str             # 用户源码
    error_message: str           # 报错信息
    current_query: str           # 本轮用户描述/问题
    fact_ledger: Annotated[list[dict], operator.add]  # 每轮事实累加

    # ── Summarizer 写入 ──
    long_focus_context: str      # fact_ledger 拼接文本

    # ── Fetcher 写入 ──
    problem_detail: str          # 题目描述
    default_template: str        # 代码模板

    # ── Diagnosis 写入 ──
    intent: str                  # 回答角色：error/teach/generate
    expert_diagnosis: str        # 分类依据（元诊断，非痛点）
    sufficiency: float           # 意图分类置信度 [0.0, 1.0]

    # ── Gatekeeper 写入 ──
    gatekeeper_verdict: str      # 决策：proceed / ask

    # ── RAG 写入 ──
    standard_solution: str       # 检索到的参考解法

    # ── Reviewer 写入 ──
    fix_suggestion: str          # 修复建议
    complexity_analysis: str     # 复杂度分析

    # ── Tutor 写入 ──
    tutor_output: str            # 教学内容

    # ── Generator 写入 ──
    generator_output: str        # 代码生成

    # ── Format / Gatekeeper 写入 — 交付 ──
    final_report: str            # 最终输出

    # ── 所有节点写入 — 遥测 ──
    metadata: Annotated[dict, _merge_metadata]
```

### 字段写入矩阵

| 字段 | 写入节点 | 主要读取节点 |
|------|----------|-------------|
| `messages` | chat.py (HumanMessage) | extractor, summarizer |
| `target_id` | extractor | fetcher, diagnosis, format |
| `source_code` | extractor | diagnosis, gatekeeper, reviewer, tutor |
| `error_message` | extractor | format |
| `current_query` | extractor | diagnosis, gatekeeper, rag |
| `fact_ledger` | extractor | summarizer |
| `long_focus_context` | summarizer | diagnosis |
| `problem_detail` | fetcher | diagnosis, gatekeeper, format |
| `intent` | diagnosis | gatekeeper, rag, format |
| `expert_diagnosis` | diagnosis | gatekeeper, rag, reviewer, tutor, generator |
| `sufficiency` | diagnosis | gatekeeper |
| `gatekeeper_verdict` | gatekeeper | (路由函数读取) |
| `standard_solution` | rag | reviewer, tutor, generator |
| `fix_suggestion` | reviewer | format |
| `complexity_analysis` | reviewer | format |
| `tutor_output` | tutor | format |
| `generator_output` | generator | format |
| `final_report` | format / gatekeeper | mirror, chat.py |
| `metadata` | 所有节点 | format, mirror |

### Reducer 策略

| 字段 | Reducer | 行为 |
|------|---------|------|
| `messages` | `add_messages` | 追加，按时间排序 |
| `fact_ledger` | `operator.add` | 列表连接，每轮追加一条 |
| `metadata` | `_merge_metadata` | 浅合并 `{**a, **b}`，永不覆盖 |

---

## 四、节点契约

### 1. extractor (前台提取器)

| 属性 | 说明 |
|------|------|
| 策略 | 正则快路径优先 → LLM 互补 → 物理校验 → 题号继承 |
| 写入 | `target_id`, `source_code`, `error_message`, `current_query`, `fact_ledger` |
| LLM 豁免 | ≤15 字短追问直接跳过 LLM |
| 代码清洗 | 自动剥离 Markdown 代码块包裹 |

### 2. summarizer (背景生成器)

| 属性 | 说明 |
|------|------|
| 策略 | 纯 Python 字符串拼接，**零 LLM 调用** |
| 输入 | `fact_ledger` |
| 输出 | `long_focus_context`（格式：`[第N轮] 题号=... 描述=...`） |

### 3. fetcher (I/O 防火墙)

| 属性 | 说明 |
|------|------|
| 查找链路 | ① `slug_map.json` → ② doocs GitHub API(5s) → ③ LeetCode GraphQL(5s) → ④ 纯题号降级 |
| 超时 | urllib `timeout=5` |
| 降级 | 全部源失败 → `FALLBACK_TEMPLATE`，不崩 Graph |

### 4. diagnosis (意图分类器)

| 属性 | 说明 |
|------|------|
| 解析方式 | `re.search` 提取 `<intent>`/`<reason>`/`<sufficiency>` XML 标签 |
| 输出 | 分类依据（元诊断），非痛点。不写代码级诊断 |
| fallback | intent 失配 → `"generate"`；sufficiency 失配 → 0.5 |

### 5. gatekeeper (决策者)

| 属性 | 说明 |
|------|------|
| 职责 | sufficiency 阈值 + 角色材料检查 |
| 输出 | `gatekeeper_verdict`: proceed / ask |
| 决策规则 | < 0.5 → ask；0.5-0.8 → 检查材料后决定；> 0.8 → 拓扑绕过 |
| 不做的 | 不传话、不评价 diagnosis、不评价 executor |

### 6. rag (意图感知检索引擎)

| 属性 | 说明 |
|------|------|
| Query 构造 | `teach` → `"算法原理和类比"`；`error` → `"标准实现和常见坑点"`；`generate` → `"最优解法"` |
| 双模检索 | 硬索引拦截(ALGO_MANIFEST) → 向量库(ChromaDB)，阈值 0.6 |
| 备降 | 知识引擎未就绪 → 返回提示信息，不影响后续执行 |

### 7-9. reviewer / tutor / generator (三专家节点)

| 属性 | reviewer | tutor | generator |
|------|----------|-------|-----------|
| 输入 | source_code, expert_diagnosis, standard_solution | expert_diagnosis, problem_detail | expert_diagnosis, problem_detail |
| 输出 | fix_suggestion + complexity_analysis | tutor_output | generator_output |
| 降级 | LLM 异常 → 保护性文案 | LLM 异常 → 保护性文案 | LLM 异常 → 保护性文案 |

## 10. format (双模板引擎)

| 属性 | 说明 |
|------|------|
| 模板 | error → 错误诊断报告，teach → 分步教学，generate → 解法 |
| 纯字符串 | **零 LLM 调用** |
| debug 模式 | `FRAME_DEBUG=1` → 追加 `[DEVELOPER TRACE]` JSON 块 |

## 11. mirror (审计镜像)

| 属性 | 说明 |
|------|------|
| 写入 | `storage/memory/{thread_id}_internal.json` + `storage/logs/{thread_id}_chat.md` |
| 约束 | **只写不读**，异常静默 |

---

## 五、基础设施

| 组件 | 选型 |
|------|------|
| Agent 框架 | LangGraph (StateGraph) |
| LLM 接口 | OpenAI / DeepSeek 兼容 API |
| 向量数据库 | ChromaDB (PersistentClient) |
| Embedding | Ollama `nomic-embed-text` |
| 持久化 | MemorySaver（默认） / RedisSaver（可选） |
| 终端交互 | prompt_toolkit |

---

## 六、异常与降级全景

| 节点 | 降级策略 |
|------|----------|
| extractor | LLM 失败 → 沿用正则结果 |
| summarizer | 零 LLM，无崩溃可能 |
| fetcher | 网络超时 → FALLBACK_TEMPLATE |
| diagnosis | 标签剥离失败 → fallback intent / sufficiency |
| gatekeeper | LLM 异常 → 保守放行 (proceed) |
| rag | ChromaDB 异常 → 仅返回索引结果，跳过向量检索 |
| reviewer/tutor/generator | LLM 异常 → 保护性文案 |
| format | 零 LLM，无崩溃可能 |
| mirror | 磁盘写入失败 → 静默跳过 |

---

## 七、依赖清单

| 包 | 用途 |
|----|------|
| `langgraph` | StateGraph 框架 |
| `langchain-openai` | LLM 调用 |
| `langchain-core` | BaseMessage, RunnableConfig |
| `chromadb` | 向量数据库 |
| `python-dotenv` | 配置加载 |
| `prompt-toolkit` | 多行终端输入 |

*内核版本: 2.1 | 最后更新: 2026-06-27*
