"""四系统对比实验 runner —— 科研对比实验的统一被试接口。

系统（对应 docs/01 第七节的实验矩阵）：
  PureRAGRunner        基线1：政策原文关键词检索 + LLM 生成（模拟通用 RAG 产品）
  PureGraphRunner      基线2：企业画像 PPR 图谱匹配（无原文验证）
  NaiveDualRunner      基线3：双通道结果并集拼接（其他队伍"双驱动"的常见做法）
  CrossValidatedRunner Ours  ：双通道 + 互验仲裁（拒答是特性）

统一接口 answer(question: EvalItem) -> SystemAnswer，由 benchmark 评分：
  集合指标（P/R/F1）+ 溯源命中率 + 拒答行为（该拒时拒/不该拒时拒）。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from policy_pilot.agent.cross_validation import ChannelResult, Verdict, cross_validate
from policy_pilot.graph.memory_engine import MemoryGraphStore


class SystemAnswer(BaseModel):
    system: str
    ids: list[str] = Field(default_factory=list)
    evidences: list[str] = Field(default_factory=list)
    refused: bool = False
    confidence: float = 0.0
    detail: str = ""


class BaseRunner(ABC):
    name: str

    @abstractmethod
    def answer(self, question: str, enterprise: dict, corpus: dict[str, str] | None = None) -> SystemAnswer:
        ...


class PureGraphRunner(BaseRunner):
    name = "pure_graph"

    def __init__(self, store: MemoryGraphStore | None = None) -> None:
        self.store = store or MemoryGraphStore.load()

    def answer(self, question, enterprise, corpus=None, **kw) -> SystemAnswer:
        hits = self.store.match_policies_for(enterprise)
        return SystemAnswer(
            system=self.name,
            ids=[h["subsidy_id"] for h in hits],
            evidences=[h.get("evidence", "") for h in hits if h.get("evidence")],
        )


class PureRAGRunner(BaseRunner):
    name = "pure_rag"

    def answer(self, question, enterprise, corpus=None, **kw) -> SystemAnswer:
        """关键词检索政策原文段落 + LLM 生成（通用 RAG 产品的最简形态）。"""
        from policy_pilot.extraction.triple_extractor import _load_json_array, get_client

        corpus = corpus or {}
        kws = [enterprise.get("industry_name", ""), "补贴", "奖励", "资助"] + enterprise.get("qualifications", [])
        scored = []
        for title, text in corpus.items():
            score = sum(1 for k in kws if k and k in text)
            if score:
                scored.append((score, title, text))
        scored.sort(key=lambda x: -x[0])
        context = "\n\n".join(f"【{t}】\n{x[:800]}" for _, t, x in scored[:3]) or "（无检索结果）"
        client = get_client()
        resp = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "glm-5.3-flash"),
            messages=[{
                "role": "user",
                "content": (
                    f"政策原文片段：\n{context}\n\n企业画像：{enterprise}\n"
                    f"问题：{question}\n"
                    '严格输出JSON：{"ids": ["可申报的支持事项(政策名#S编号,无编号则用政策名#S1)"], '
                    '"evidences": ["依据的原文片段"], "无结果": true|false}'
                ),
            }],
            temperature=0.0,
            extra_body={"thinking": {"level": os.getenv("LLM_THINKING_LEVEL", "low")}},
        )
        items = _load_json_array(resp.choices[0].message.content or "")
        if not items:
            return SystemAnswer(system=self.name, refused=True, detail="LLM输出解析失败")
        it = items[0]
        return SystemAnswer(
            system=self.name,
            ids=[str(i) for i in it.get("ids", [])],
            evidences=[str(e) for e in it.get("evidences", [])][:5],
            refused=bool(it.get("无结果")),
        )


class NaiveDualRunner(BaseRunner):
    """基线3：两通道并集拼接，无互验、无拒答。"""

    name = "naive_dual"

    def __init__(self, store: MemoryGraphStore | None = None) -> None:
        self.graph = PureGraphRunner(store)

    def answer(self, question, enterprise, corpus=None, **kw) -> SystemAnswer:
        g = self.graph.answer(question, enterprise)
        r = PureRAGRunner().answer(question, enterprise, corpus)
        merged = list(dict.fromkeys(g.ids + r.ids))  # 并集去重
        return SystemAnswer(
            system=self.name, ids=merged,
            evidences=g.evidences + r.evidences,
            detail=f"graph={len(g.ids)} rag={len(r.ids)} 直接拼接",
        )


def align_ids(rag_ids: list[str], graph_ids: list[str]) -> list[str]:
    """两通道 ID 规范对齐：RAG 生成的名称（可能带书名号/缺前缀/缺#S编号）
    映射到图谱 ID 体系（最长包含匹配），对不上的保留原样。"""
    def clean(s: str) -> str:
        return s.replace("《", "").replace("》", "").replace(" ", "").replace("苏州市", "")

    def pkey(s: str) -> str:
        return clean(str(s).split("#")[0])

    aligned = []
    for rid in rag_ids:
        rc, best = clean(rid), ""
        for gid in graph_ids:
            gc = clean(gid)
            if rc in gc or gc in rc or pkey(rid) == pkey(gid):  # 三级：原文/清洗包含/政策级相等
                if len(gid) > len(best):
                    best = gid
        aligned.append(best or rid)
    return aligned


class CrossValidatedRunner(BaseRunner):
    """Ours：双通道 + 互验仲裁。"""

    name = "cross_validated"

    def __init__(self, store: MemoryGraphStore | None = None) -> None:
        self.graph = PureGraphRunner(store)

    def answer(self, question, enterprise, corpus=None, **kw) -> SystemAnswer:
        g = self.graph.answer(question, enterprise)
        r = PureRAGRunner().answer(question, enterprise, corpus)
        rag_ids = align_ids(r.ids, g.ids)  # ID 规范对齐后互验
        gc = ChannelResult(channel="graph", ids=g.ids, evidences=g.evidences)
        rc = ChannelResult(channel="rag", ids=rag_ids, evidences=r.evidences)
        v = cross_validate(gc, rc)
        if v.verdict == Verdict.REJECTED:
            return SystemAnswer(system=self.name, refused=True, confidence=0.0,
                                detail=f"拒答：{v.conflict}")
        if v.verdict == Verdict.RETRY:
            r2 = PureRAGRunner().answer(question, enterprise, corpus)  # 仲裁重查一次
            v = cross_validate(gc, ChannelResult(channel="rag", ids=r2.ids, evidences=r2.evidences),
                               retry_once=ChannelResult(channel="rag", ids=r2.ids, evidences=r2.evidences))
            if v.verdict == Verdict.REJECTED:
                return SystemAnswer(system=self.name, refused=True, confidence=0.0,
                                    detail=f"仲裁后仍拒答：{v.conflict}")
        return SystemAnswer(
            system=self.name, ids=v.agreed_ids, evidences=g.evidences + r.evidences,
            confidence=v.confidence,
            detail=f"裁决={v.verdict.value}",
        )


def get_runner(name: str, store: MemoryGraphStore | None = None) -> BaseRunner:
    return {
        "pure_graph": lambda: PureGraphRunner(store),
        "pure_rag": PureRAGRunner,
        "naive_dual": lambda: NaiveDualRunner(store),
        "cross_validated": lambda: CrossValidatedRunner(store),
    }[name]()
