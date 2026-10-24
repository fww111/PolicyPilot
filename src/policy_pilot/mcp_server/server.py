"""
Nexent 自定义 MCP 工具服务 —— 检索-推理双驱动中"推理 Agent"的武器库。

三个工具（赛题要求"MCP 协议深度集成"）：
  1. query_policy_graph      图谱多跳查询（匹配/废止链/冲突）
  2. extract_enterprise_profile 从用户自述中抽取结构化企业画像
  3. check_policy_validity   政策时效性检查（现行有效？被谁废止？）

接入 Nexent（官方文档验证的流程）：
  1. 启动本服务（SSE/HTTP 模式，默认端口 8765）：
     MCP_TRANSPORT=sse uv run python -m policy_pilot.mcp_server.server
  2. Nexent UI -> 智能体开发 -> 工具页签 -> "MCP配置" -> 添加：
     名称 policy_pilot（仅字母数字下划线连字符）
     URL  http://host.docker.internal:8765/sse
     （Docker 部署的 Nexent 访问宿主机服务必须用 host.docker.internal）
  3. 创建智能体时在工具列表勾选本服务暴露的 5 个工具。
"""

from __future__ import annotations

import json
import re

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServerBase
except ModuleNotFoundError:  # mcp 2.x：FastMCP 已改名 MCPServer
    from mcp.server.mcpserver import MCPServer as MCPServerBase

app = MCPServerBase("policy-pilot-graph")


@app.tool()
def query_policy_graph(query_type: str, payload: str) -> str:
    """政策知识图谱多跳查询。

    Args:
        query_type: match | supersede_chain | conflicts 三种查询之一
        payload: JSON 字符串。
                 match -> {"industry_gb_code":"I65","size":"小型","qualifications":[],"region_code":"440305"}
                 supersede_chain -> {"policy_id":"深府规〔2024〕3号"}
                 conflicts -> {"subsidy_id":"...#S1"}
    """
    from policy_pilot.graph.memory_engine import get_store

    store = get_store()  # GRAPH_ENGINE=memory(默认)/neo4j
    if not hasattr(store, "g"):  # neo4j 模块形态：函数集合
        from policy_pilot.graph import graph_store as store
    data = json.loads(payload)
    try:
        if query_type == "match":
            rows = store.match_policies_for(data)
        elif query_type == "supersede_chain":
            rows = store.trace_supersede_chain(data["policy_id"])
        elif query_type == "conflicts":
            rows = store.find_conflicts(data["subsidy_id"])
        else:
            return json.dumps({"error": f"未知 query_type: {query_type}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "hint": "检查图引擎/数据库是否可用"}, ensure_ascii=False)
    return json.dumps(rows, ensure_ascii=False, indent=2)


@app.tool()
def extract_enterprise_profile(description: str) -> str:
    """从企业自述文本中抽取结构化画像（行业/规模/成立年限/资质/区域）。

    供推理 Agent 在 match 查询前调用，输出与本体 Enterprise 字段对齐。
    行业字段归一为 GB/T 4754 国标名（与图谱类别节点同名，保证匹配命中）。
    """
    import json as _json
    import re

    from policy_pilot.ontology.gb4754 import normalize_industry

    size = ""
    if re.search(r"微型", description):
        size = "微型"
    elif re.search(r"小型|小企业|小微企业", description):
        size = "小型"
    elif re.search(r"中型", description):
        size = "中型"
    elif re.search(r"大型", description):
        size = "大型"

    founded_years = None
    m = re.search(r"(?:成立|注册)(?:不超过|不足|满|已?经)?(\d{1,2})年", description)
    if m:
        founded_years = int(m.group(1))

    employees = None
    m = re.search(r"(\d{2,6})\s*(?:名|个)?(?:员工|职工|人员|人)", description)
    if m:
        employees = int(m.group(1))

    quals = []
    for q in ("高新技术企业", "专精特新", "科技型中小企业", "瞪羚企业", "独角兽"):
        if q in description or (q == "高新技术企业" and "高企" in description):
            quals.append(q)

    industry_name = ""
    industry_gb_code = ""
    norm = normalize_industry(description)
    if norm:
        industry_gb_code, industry_name = norm[0], norm[1]

    profile = {
        "name": "",
        "industry_gb_code": industry_gb_code,
        "industry_name": industry_name,
        "size": size,
        "founded_years": founded_years,
        "region_code": "",
        "qualifications": quals,
        "employees": employees,
        "revenue_wan": None,
        "_note": "行业已归一为GB/T 4754国标名；query_policy_graph 的 payload 请直接使用本画像的 industry_name 与 size 字段",
    }
    return _json.dumps(profile, ensure_ascii=False, indent=2)


@app.tool()
def check_policy_validity(policy_id: str) -> str:
    """检查政策时效性：当前状态 + 废止链（若有）。决策溯源的时效维证据。"""
    from policy_pilot.graph.memory_engine import get_store

    try:
        store = get_store()
        if not hasattr(store, "g"):
            from policy_pilot.graph import graph_store as store
        chain = store.trace_supersede_chain(policy_id)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    return json.dumps(
        {
            "policy_id": policy_id,
            "supersede_chain": chain,
            "note": "chain 为空且 status=现行有效 时，输出仍以 Policy 节点 status 字段为准",
        },
        ensure_ascii=False,
        indent=2,
    )


@app.tool()
def check_eligibility(subsidy_id: str, enterprise_profile: str) -> str:
    """资格判断（独有创新②）：对企业画像精确执行该支持事项的申报条件谓词。

    Args:
        subsidy_id: 支持事项ID（如 苏州市促进入境旅游若干措施#S1）
        enterprise_profile: JSON 企业画像，字段对齐本体 Enterprise
            （industry_name/size/founded_years/employees/revenue_wan/qualifications/region_code）
    输出三值语义：满足 / 不满足 / 待补信息，附逐条件判定明细（可解释溯源）。
    """
    from policy_pilot.eval.predicate_exec import check_eligibility as _check
    from policy_pilot.graph.memory_engine import MemoryGraphStore

    try:
        ent = json.loads(enterprise_profile)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"画像JSON无效: {e}"}, ensure_ascii=False)
    store = MemoryGraphStore.load()
    conds = _load_conditions(store, subsidy_id)
    if not conds:
        return json.dumps({"error": f"图谱中未找到 {subsidy_id} 的条件谓词"}, ensure_ascii=False)
    return json.dumps(_check(conds, ent), ensure_ascii=False, indent=2)


def _load_conditions(store, subsidy_id: str) -> list:
    """从图谱边的 evidence 中恢复该事项的条件谓词（W2-B2 抽取侧将直接产出 Condition 节点）。"""
    from policy_pilot.ontology.policy_ontology import Condition

    conds = []
    for u, v, d in store.g.in_edges(subsidy_id, data=True):
        if d.get("relation") == "APPLIES_TO" and str(v).startswith("#C"):
            conds.append(Condition(condition_id=str(v), field="industry_name", op="CONTAINS",
                                   value=str(v).split("value=")[-1].rstrip("}"), description=d.get("evidence", "")))
    return conds


@app.tool()
def cross_validate_answers(graph_answer: str, rag_answer: str) -> str:
    """双通道互验仲裁（独有创新①）：对图谱通道与检索通道的结论做一致性裁决。

    Args:
        graph_answer: JSON {"ids": ["事项ID..."], "evidences": ["图谱路径..."]}
        rag_answer: JSON {"ids": ["事项ID..."], "evidences": ["政策原文引用..."]}
    返回四级裁决：采纳/降置信采纳/仲裁重查/拒答（拒答附两通道分歧依据）。
    """
    from policy_pilot.agent.cross_validation import ChannelResult, cross_validate

    try:
        g = ChannelResult(channel="graph", **json.loads(graph_answer))
        r = ChannelResult(channel="rag", **json.loads(rag_answer))
    except Exception as e:
        return json.dumps({"error": f"入参无效: {e}"}, ensure_ascii=False)
    return cross_validate(g, r).model_dump_json(indent=2)


_AUTH_PATTERNS = [  # (pattern, level, name) —— 效力层级启发式（docs/10 §3.3）
    (r"国令|主席令|法律", 1, "法律"),
    (r"国务院令|行政法规", 2, "行政法规"),
    (r"国办发|部令|部门规章|工信部|财政部|人民银行", 3, "部门规章/文件"),
    (r"省政发|省政府令|省人大|苏政", 4, "省级法规/规章"),
    (r"市政|市政府|苏府|区政", 5, "市级规范性文件"),
]


def _classify_authority(policy_id: str) -> tuple[int, str]:
    from policy_pilot.graph.memory_engine import MemoryGraphStore

    s = MemoryGraphStore.load()
    node = s.g.nodes.get(policy_id, {})
    text = f"{policy_id} {node.get('title', '')}"
    for pat, level, name in _AUTH_PATTERNS:
        if re.search(pat, text):
            return level, name
    return 5, "规范性文件(默认)"


@app.tool()
def check_authority_level(id_a: str, id_b: str) -> str:
    """效力层级校验（审查场景）：判断 a 是否优先于 b（上位法优先原则）。

    层级：1法律 > 2行政法规 > 3部门规章 > 4省级 > 5市级规范性文件。
    """
    la, na = _classify_authority(id_a)
    lb, nb = _classify_authority(id_b)
    rel = "unknown" if (la == 5 and lb == 5 and na.startswith("默认")) else ("a_superior" if la < lb else "b_superior" if lb < la else "same")
    return json.dumps({"id_a": id_a, "level_a": la, "name_a": na,
                       "id_b": id_b, "level_b": lb, "name_b": nb,
                       "relation": rel,
                       "note": "层级由文号/标题启发式判定；标注集场景以人工标注为准"}, ensure_ascii=False, indent=2)


@app.tool()
def trace_conflict_evidence(id_a: str, id_b: str) -> str:
    """冲突证据溯源（审查场景）：返回两政策的冲突/废止关系与逐字原文摘录。

    查询 CONFLICTS_WITH / SUPERSEDES 双向边；配合 verify_citations_tool
    可实现"生成-核验-打回"的确定性闭环。
    """
    from policy_pilot.graph.memory_engine import MemoryGraphStore

    s = MemoryGraphStore.load()
    edges = []
    for u, v, d in s.g.edges(data=True):
        if {u, v} == {id_a, id_b} and d["relation"] in ("CONFLICTS_WITH", "SUPERSEDES"):
            edges.append({"relation": d["relation"], "from": u, "to": v,
                          "evidence": d.get("evidence", ""), "source": d.get("source", "")})
    return json.dumps({"found": len(edges) > 0, "edges": edges,
                       "note": "evidence 为抽取时摘录原文，可经 verify_citations_tool 逐字复核"}, ensure_ascii=False, indent=2)


@app.tool()
def verify_citations_tool(answer: str) -> str:
    """引用逐字核验（Verifier 节点专用，docs/10 核心机制）。

    对回答中每一条引用做规范化逐字核验：任何未逐字出现在源文件中的
    引用都会被拒绝（打回修正）。pass_rate < 1 时上游应打回重写，
    确保决策证据链 100% 可溯源。
    """
    from pathlib import Path as _Path

    from policy_pilot.agent.verifier import verify_citations as _verify

    global _VERIFY_CORPUS
    try:
        _VERIFY_CORPUS
    except NameError:
        _VERIFY_CORPUS = {}
        from policy_pilot.parser.doc_parser import parse_any as _parse
        for f in _Path(__file__).resolve().parents[3].glob("data/raw/*.html"):
            try:
                doc = _parse(f)
                if len(doc.full_text) > 200:
                    _VERIFY_CORPUS[f.stem[:40]] = doc.full_text
            except Exception:
                continue
    return _verify(answer, _VERIFY_CORPUS).model_dump_json(indent=2)


if __name__ == "__main__":
    import os

    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        app.run(transport="sse", host="0.0.0.0", port=int(os.getenv("MCP_PORT", "8765")))
    else:
        app.run(transport="stdio")
