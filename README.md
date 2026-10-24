# PolicyPilot · 可进化惠企政策决策智能体

> 第十一届华为ICT大赛创新赛 · 赛题3：基于华为 ModelEngine Nexent 打造可进化决策智能体

**一句话定位**：现有政策匹配产品停在"要素标签比对 + 人工复核"，通用 GraphRAG 框架缺乏政策的时效、冲突、层级语义；本工作在 Nexent 上构建**可进化、可溯源**的政策决策智能体，并开源首个政务政策匹配评测基准。

## 架构

```
政策文件(全公开)                    企业用户提问
     │                                  │
     ▼                                  ▼
┌─────────────┐   ┌──────────────┐   ┌─────────────────────────┐
│ 爬虫/解析层  │──▶│ 本体引导抽取  │──▶│      Neo4j 知识图谱       │
│ MinerU+pdfplumber│ LLM+置信度分流 │   │ 时效/冲突/层级 三维本体    │
└─────────────┘   │ +人工复核闭环  │   └───────────┬─────────────┘
                  └──────────────┘               │ MCP 工具
                                                 ▼
                                  ┌─────────────────────────┐
                                  │   Nexent 双驱动智能体      │
                                  │  检索Agent(RAG原文证据)    │
                                  │  推理Agent(图谱多跳) 互验   │
                                  └───────────┬─────────────┘
                                              ▼
                              可申政策清单 + 三级溯源链(文号+条款+图谱路径)
```

## 目录结构

| 路径 | 职责 | 对应创新点 |
|---|---|---|
| `src/policy_pilot/ontology/` | 政策本体定义（三维关系+实体） | 创新点1 |
| `src/policy_pilot/extraction/` | LLM 本体引导抽取 + 置信度分流 + 人工复核闭环 | 创新点2 |
| `src/policy_pilot/crawler/` | 政府公开政策文件爬取（限速礼貌爬取） | 数据层 |
| `src/policy_pilot/parser/` | 多模态解析（MinerU 主力 / pdfplumber 回退） | 多模态题眼 |
| `src/policy_pilot/graph/` | Neo4j 存储 + 多跳查询（废止链/冲突/匹配） | 创新点1 |
| `src/policy_pilot/mcp_server/` | 3 个自定义 MCP 工具，接入 Nexent | 编排题眼 |
| `src/policy_pilot/eval/` | 自建评测基准（4 类题型） | 附加分 |
| `data/` | raw原始 / parsed解析 / kg图谱 / eval评测 | — |
| `docs/` | 调研、计划、量化数据记录 | 文档 |

## 快速开始

```bash
# 1. 安装依赖（uv 会自动建 .venv）
uv sync

# 2. 配置环境变量
cp .env.example .env   # 填入你的 LLM_API_KEY 等

# 3. 健康检查（四项全绿即环境就绪）
uv run python scripts/setup_check.py

# 4. 冒烟测试（不依赖外部服务）
uv run pytest -v

# 5. 启动 MCP 工具服务（供 Nexent 接入）
uv run python -m policy_pilot.mcp_server.server
```

Neo4j 一行启动：

```bash
docker run -d --name policy-neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/policy123 neo4j:5
```

## 里程碑

- [ ] W1 环境就绪：Nexent 本地跑通 + 首批 30 份政策试爬
- [ ] W2 数据集：300~500 份入库 + 本体 schema 定稿 + 10 份抽取实验
- [ ] W3 图谱：全量构建 + 知识库切片对比
- [ ] W4 编排：Nexent 双驱动 Agent + 3 MCP 工具，端到端问答
- [ ] W5 评测：200 题基准 + 三系统对比 + Demo
- [ ] W6 文档：开发设计文档（对齐 4×25% 评分）

## 评分对照

| 评分项 | 本仓库对应 |
|---|---|
| 智能体编排与MCP/Skill深度集成 25% | mcp_server/ + Nexent Skills 工作流 |
| 资产激活业务价值 25% | 沉睡政策文件激活 + 溯源解决"人工复核"痛点 |
| 算法创新性 25% | 低资源半自动本体构建（量化记录见 docs/03） |
| 交互体验与能力沉淀 25% | 溯源链可视化 + 可迁移 Skill 模板（A市→B市） |

详细调研依据与相关工作对比见 [docs/01-调研与创新点.md](docs/01-调研与创新点.md)。
