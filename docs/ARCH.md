# 架构全貌

## 分层抽象

```
L8 — 信息载体
  state.py (AgentState)      ← 每个字段有唯一写者，主权不可侵犯
  metadata reducer            ← 所有节点写入，浅合并永不覆盖

L5-L6 — 拓扑与路由
  graph.py (StateGraph)       ← 3 条条件路由 + 双模式
    diagnosis → sufficiency 路由  ← Gatekeeper 三级决策
    gatekeeper → verdict 路由     ← ask 走 mirror，proceed 走执行
    rag → intent 路由             ← 分流到具体专家节点

L3-L4 — 认知节点（11 节点）
  extractor      正则 + LLM 互补提取题号/代码/报错
  summarizer     纯字符串拼接，零 LLM
  fetcher        三优先级查找（本地→doocs→GraphQL）
  diagnosis      意图分类（error/teach/generate），XML 标签输出
  gatekeeper     材料审核决策（proceed/ask），LLM 判断
  rag            意图感知向量检索（ChromaDB + 硬索引）
  reviewer       修复方案 + 复杂度分析（LLM）
  tutor          苏格拉底式教学（LLM）
  generator      最优解法生成（LLM）
  format         按 intent 模板组装报告，纯字符串，零 LLM
  mirror         审计镜像，只写不读，异常静默

L1 — 基础设施
  LangGraph (StateGraph)
  OpenAI / DeepSeek 兼容 API
  ChromaDB + Ollama Embedding
  prompt_toolkit（多行终端交互）
  slug_map.json（191 题本地映射）
  ALGO_MANIFEST.json（214 题索引清单）
  filesystem（books/, storage/, knowledge_db/）
```

## 数据流向

```
START → extractor → summarizer → fetcher → diagnosis
                                                │
                                         [sufficiency 路由]
                                       > 0.8         ≤ 0.8
                                         │             │
                                        rag       gatekeeper
                                         │        ask    proceed
                                    [intent 路由]    │       │
                                   ┌────┼────┐    mirror    rag
                                error teach generate      [intent 路由]
                                                            ┌────┼────┐
                                                          error teach generate
                                                            │     │     │
                                                          format → mirror → END
```

**三条条件路由**：
1. **diagnosis 后** — `_route_after_diagnosis`：sufficiency > 0.8 走 Flash 快路径，否则走 gatekeeper
2. **gatekeeper 后** — `_route_after_gatekeeper`：ask 走 mirror，proceed 按 intent 走 RAG
3. **RAG 后** — `_route_after_rag`：按 intent 分流到 reviewer / tutor / generator

## 节点职责

| 节点 | 输入（读） | 输出（写） | LLM 调用 |
|------|-----------|-----------|---------|
| extractor | messages（用户输入） | target_id, source_code, error_message, current_query, fact_ledger | 条件触发 |
| summarizer | fact_ledger | long_focus_context | 否（纯字符串） |
| fetcher | target_id | problem_detail, default_template | 否（仅网络 I/O） |
| diagnosis | current_query, long_focus_context, source_code | intent, expert_diagnosis, sufficiency | 是 |
| gatekeeper | intent, sufficiency, source_code, current_query | gatekeeper_verdict, final_report（ask 时） | 是 |
| rag | intent, expert_diagnosis, current_query | standard_solution | 否（仅检索） |
| reviewer | source_code, expert_diagnosis, standard_solution | fix_suggestion, complexity_analysis | 是 |
| tutor | expert_diagnosis, problem_detail, source_code | tutor_output | 是 |
| generator | expert_diagnosis, problem_detail | generator_output | 是 |
| format | intent + 各专家产出字段 | final_report | 否（纯拼接） |
| mirror | final_report + metadata | （磁盘写入） | 否（仅 I/O） |

## 双模式路由

| 模式 | 条件 | 路径 | 说明 |
|------|------|------|------|
| Flash 快路径 | sufficiency > 0.8 | diagnosis → rag → intent → executor | Gatekeeper 被拓扑绕过，延迟最小 |
| 审核路径 | sufficiency ≤ 0.8 | diagnosis → gatekeeper → (proceed → rag / ask → mirror) | 每一轮都经过门卫审核 |
| Pro 模式内 | verdict = proceed | gatekeeper 写入 passed_check: true | 即使放行也留下检查记录 |

## 当前进度

| 模块 | 状态 | 说明 |
|------|------|------|
| 前置链路（extractor → summarizer → fetcher） | ✅ | 可运行 |
| diagnosis 意图分类 + sufficiency | ✅ | 元分类输出，不越界写痛点 |
| gatekeeper 三级决策 | ✅ | < 0.5 ask / 0.5-0.8 检查 / > 0.8 快路径 |
| RAG 双模检索 | ✅ | 硬索引 + 向量检索，阈值 0.6 |
| 三专家节点（reviewer / tutor / generator） | ✅ | 各司其职，互不越界 |
| format 报告组装 | ✅ | 纯字符串 |
| mirror 审计输出 | ✅ | 只写不读，异常静默 |
| chat.py 多行终端交互 | ✅ | prompt-toolkit，Alt+Enter 提交 |
| Flash / Pro 双模式 | ✅ | 拓扑 + prompt 双层面实现 |
| Streamlit Web 界面 | 🔄 | 开发中 |
| LangSmith 全链路追踪 | 📋 | 规划中 |
| RAG 评估体系 | 📋 | 规划中 |
| 代码沙箱 + 反思节点 | 📋 | 规划中 |
| 系统自更新机制 | 📋 | 规划中 |
| 多专家顺序协作 | 📋 | 规划中 |

## 设计约束

- **节点主权**：每个字段只有一个写者节点，禁止跨界写入
- **无环拓扑**：图结构设计确保没有回流，避免节点间循环依赖
- **知道不知道**：Gatekeeper 在信息不足时有权拒绝执行，而非强行生成
- **LLM 降级**：每个 LLM 节点都有独立的 try-except 降级文案，不阻塞图执行
- **只写不读**：mirror 节点不返回任何业务字段，审计副作用不侵入主流程
