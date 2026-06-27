# LangGraph-Algo-System — 认知功能拓扑化 Agent 系统

<div align="center">

**不是"调 API → 出答案"的管道。是将通用 Agent 的"想-做-审"拆解为图拓扑上独立认知节点的架构实验。**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![LangGraph](https://img.shields.io/badge/LangGraph-latest-green)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)]()

</div>

---

## 为什么不是又一个 Agent Demo？

当前主流的 Agent 实现大多基于 ReAct 模式——一个 LLM 在循环中同时承担推理、决策、执行、判断全部角色。这种设计有两个无法回避的问题：

1. **认知混淆** — 同一个模型既在判断"信息够不够"，又在生成答案。它不会承认自己不知道
2. **边界流失** — 模型的注意力被分散到所有环节，没有一个环节由专门的模块深度处理

LangGraph-Algo-System 换了一种方式：**将认知功能分解为多个独立节点，每个节点只读/写自己的状态字段，通过 LangGraph 的有向图拓扑决定数据流路径。**

这意味着：

- **Gatekeeper** 不知道下游是 tutor 还是 generator，它只判断"当前信息是否足以执行"
- **Diagnosis** 不知道自己的分类结果会被谁消费，它只做意图分类
- **Executor** 不质疑上游的分类是否正确，它只在自己的领域内生成内容

每一个节点在自己的世界里是孤独的。但它们的协作构成了一个完整的认知系统。

---

## 当前拓扑（11 节点 + 3 条件路由）

```
START → extractor → summarizer → fetcher → diagnosis
                                                │
                                         [sufficiency 路由]
                                       > 0.8         ≤ 0.8
                                         │             │
                                        rag       gatekeeper
                                         │        ask     proceed
                                    [intent 路由]    │       │
                                   ┌────┼────┐    mirror    rag
                                error teach generate      [intent 路由]
                                                            ┌────┼────┐
                                                          error teach generate
                                                            │     │     │
                                                          format → mirror → END
```

---

## 关键设计

### Gatekeeper 三级决策

基于 `sufficiency`（意图分类置信度）的三级路由——这是系统"知道自己不知道"的能力来源：

| 区间 | 行为 | 场景示例 |
|------|------|---------|
| < 0.5 | 直接 ask。信息太少，连该问什么都不知道 | 用户说"帮我"→ 系统："请问你需要什么帮助？" |
| 0.5 ~ 0.8 | 按角色检查材料。够则放行，不够则 ask | 用户说"394"→ 系统确认："你想了解解法还是思路？" |
| > 0.8 | Flash 快路径。Gatekeeper 被拓扑绕过 | 用户说"394 题怎么做"→ 直接走生成 |

### 节点主权（Node Sovereignty）

`AgentState` 中每一个字段有且只有一个写者节点。没有两个节点竞争同一字段的写入权，因此不需要锁、不需要事务、不需要运行时仲裁。系统行为通过图拓扑即可预测。

如果一个问题出现，只需要看 `state.py` 中该字段的归属，就知道该去哪个节点排查。

### 无环拓扑—结构性防回流

节点之间没有环。不是图框架限制——是从架构层面切断了回流存在的理由。没有两个节点需要互相等待对方的输出，没有数据需要经过"你觉得我的判断对吗"这种循环验证。

---

## 快速开始

```bash
git clone https://github.com/BeMaster666/LangGraph-Algo-System.git
cd LangGraph-Algo-System
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入你的 API Key
python mind/chat.py
```

调试模式（查看每个节点的运行时日志）：
```bash
python mind/chat.py --debug
```

---

## 开发路线

| 阶段 | 状态 | 内容 |
|:-----|:-----|:------|
| **核心引擎** | ✅ 已完成 | 11 节点图拓扑、Gatekeeper 三级决策、节点主权架构、双模式路由、RAG 检索引擎、审计镜像 |
| **交互层** | 🔄 开发中 | Streamlit Web 界面、终端交互优化、上下文可视化 |
| **可观测性** | 🔄 开发中 | LangSmith 全链路追踪、Debug 面板、节点延迟监控 |
| **评估体系** | 📋 规划中 | RAGAS 检索质量评估、Embedding 对比实验、Bad Case 闭环 |
| **沙箱执行** | 📋 规划中 | 代码沙箱执行 + 反思验证节点 + Flash/Pro 双模式 |
| **系统自更新** | 📋 规划中 | 用户偏好收集、题库索引自动更新、fact_ledger 记忆压缩与归档 |
| **检索增强** | 📋 规划中 | 多路召回、Re-ranker 重排、语义切分对比实验 |

---

## 项目结构

```
LangGraph-Algo-System/
├── mind/                    # 核心代码
│   ├── graph.py             # StateGraph 拓扑 + 3 条条件路由
│   ├── state.py             # AgentState—每个字段有唯一写者
│   ├── chat.py              # 交互终端 (prompt_toolkit)
│   ├── knowledge_engine.py  # 知识检索引擎
│   ├── nodes/               # 11 个认知节点
│   │   └── ...              # extractor → gatekeeper → tutor → mirror
│   ├── books/               # 知识库源文件（400+ 算法题解与教程）
│   └── storage/             # 审计输出
├── docs/
│   ├── KERNEL.md            # 系统契约（宪法 + 数据流 + 降级全景）
│   ├── ARCH.md              # 架构说明
│   └── TEST_CASES.md        # 测试用例集
├── tests/                   # 自动化测试
└── README.md
```

---

## 技术栈

| 类别 | 选型 |
|------|------|
| Agent 框架 | LangGraph（StateGraph + 条件路由） |
| LLM 接口 | OpenAI / DeepSeek 兼容 API |
| 向量检索 | ChromaDB + Ollama Embedding |
| 持久化 | MemorySaver / RedisSaver |
| 终端交互 | prompt_toolkit（多行编辑 + 键绑定） |
| 计划接入 | Streamlit / LangSmith / RAGAS / Re-ranker |

---

## 设计理念

- **自由** — 节点可以不做什么。Gatekeeper 有权拒绝执行并说"不知道"
- **平等** — 主权边界不可侵犯。没有节点可以修改另一个节点的字段
- **纯粹** — 节点不知道边界外的事存在。它们在自己的世界里孤独地协作

---

## License

MIT © 2026 BeMaster666
