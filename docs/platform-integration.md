# Nexent 平台真实接入与运行证据（B0）

> 日期：2026-10-25。环境：本机 Docker Desktop + Nexent 全栈容器（基线 `5336b771`）。
> 本文档记录领域 MCP 工具层接入真实 Nexent 平台的完整过程、修复的问题与运行证据。

## 1. 接入架构

```text
Nexent Web (3000) → nexent-runtime (5014)          ← Agent 执行（GLM-5.3-Flash）
        Agent ──MCP 协议──> http://host.docker.internal:8765/mcp
                                 = competition/src/competition/mcp/server.py（http transport）
                                     └─ DomainService（scenario_d 合成样例）
```

- 领域 MCP server 以 `uv run python src/competition/mcp/server.py --transport http --port 8765` 常驻。
- 7 个工具（search_assets / get_evidence / resolve_entity / read_table_region / execute_plan / replay_decision / analyze_change_impact）经 `POST /api/mcp/add` 注册，`GET /api/tool/scan_tool` 入库（tool_id 79–85），`GET /api/mcp/tools?mcp_id=2` 确认 Nexent 经 MCP 协议真实拉取。
- Agent「质量证据审核智能体」（agent_id=2）绑定 7 个工具与既租户模型（model_id=1，智谱 GLM-5.3-Flash）。

## 2. 接入过程修复的问题（如实记录）

| 问题 | 根因 | 修复 |
|---|---|---|
| 容器无法访问宿主 server | 需要 host 网关地址 | server.py 增加 `--transport http`；URL 用 `host.docker.internal:8765` |
| FastMCP 拒绝 `**kwargs` 工具签名 | 协议层需具体签名 | 统一为显式 `payload: str`（JSON 编码），注册表侧仍逐键校验 |
| 数据库 schema 缺列（`duty_prompt` 等） | 镜像升级到 5336b77 后迁移未重放 | 按 `deploy/sql/migrations/README.md` 机制顺序重放 v1–v2.8.0（幂等）；两处 `model_record_t/knowledge_record_t` 报错为旧库无可选表，非阻塞 |
| Agent 更新 401 | 该端点要求 Authorization 头 | cookie 之外补 `Authorization: Bearer <JWT>` |
| JWT 过期 | 会话 7200 秒 | 重新登录刷新 |
| 运行时 "Model not found" | 三层叠加：超管 `user_tenant_t.tenant_id` 为空；本轮创建记录挂在字面量租户 `tenant_id`；模型 `model_type` 误用 "main"（列表只取 "llm"） | 超管并入既有租户 `53fdeb75`；模型/Agent/MCP/工具记录租户统一修正；发现租户下已有可用模型（早期 e2e 配置，model_id=1/2），Agent 改绑 model_id=1 |
| AgentConfig 校验失败 `max_steps=None` | 创建时未设 | 补 `max_steps=30` |
| L-2026-11 被模型答成"超出公差" | GLM 把 EvidenceItem.supports=false 误读为 refuted——**计划第 16 节"模型裁判偏差"的真实复现** | 提示词加铁律：四态必须逐字引用 `decision.status`；重跑后正确输出 unknown |

## 3. 平台级运行证据（对话流全量存档于 `docs/evidence/`）

### 场景一：L-2026-10（`run-L2026-10-supported.sse`）

Agent 经平台真实调用 execute_plan → get_evidence（4 次）→ replay_decision，最终回答包含：

- 四态结论 **supported**，决策编号 DEC-T1-L-2026-10
- 三源证据锚点表：ANC-0002（检验表第 2 行第 5 列 `4.8`）/ ANC-0010（SPEC-D v1 条款 5.2 `0.005`）/ ANC-0008（校准 CAL-M07-2026 有效期）
- 判定逻辑四步（适用性→公差→校准窗口→聚合）与规则 ID
- 当前知识复算（replay_decision 返回 changed=false）

### 场景二：L-2026-11（`run-L2026-11-unknown.sse`）

- 四态结论 **unknown**（逐字引用 status）
- 缺失项逐字引用："re-inspection: measurement outside calibration validity"
- 正确传达"校准有效期外测量不可作判定依据，需复检"——降级语义在平台上成立

工具真值核对（同一代码路径直查）：L-2026-10 → supported / missing=[]；L-2026-11 → unknown / missing=['re-inspection: ...']。平台回答与工具真值一致。

## 4. 结论与边界

- **结论**：计划第 17 节"核心业务通过真实 Nexent 的 MCP 运行"达成；受限计划、四态结论、证据锚点、降级语义全部在真实平台链路上成立。这不是独立脚本的模拟运行。
- **边界**：合成样例（`synthetic: true`）验证机制，不代表真实企业数据；模型裁判偏差需持续用提示词约束 + 结构化字段引用对抗；`server.py` 的 demo 身份映射（tenant="demo"）在多租户生产化时需替换为真实认证上下文。
