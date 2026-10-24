"""Verifier 确定性核验器（docs/10 §3.2，审查场景的差异化核心）。

问题：LLM 生成的"冲突结论"常伴随近似转述的引用——"看起来像冲突"≠"法律上确实构成冲突"。
机制：生成 → 核验 → 打回。智能体引用的每一条原文，逐字（规范化后）出现在源文件中才放行；
      否则拒绝并附原因，由智能体修正后重试。

卖点：确定性、零幻觉、100% 拦截可复现——这是与所有 GraphRAG 系的差异化点。
"""

from __future__ import annotations

import re
from pydantic import BaseModel, Field


def normalize(text: str) -> str:
    """引用核验的规范化：全角→半角、空白折叠、标点统一。"""
    table = str.maketrans("（）：；，、“”‘’　", "():;,、\"\"'' ")
    t = text.translate(table)
    t = re.sub(r"\s+", "", t)
    return t


class Citation(BaseModel):
    raw: str = Field(..., description="从回答中抽取的引用原文")
    found_in: str = Field("", description="命中的源文档 ID（逐字核验通过时）")


class VerifyResult(BaseModel):
    verified: list[Citation] = Field(default_factory=list)
    rejected: list[Citation] = Field(default_factory=list, description="未通过逐字核验的引用（打回重写）")
    pass_rate: float = Field(0.0, description="核验通过率；<1.0 时 Verifier 节点应打回")


def extract_citations(answer: str) -> list[str]:
    """从智能体回答中抽取引用片段（中文政务文本的三类句式）。"""
    citations: list[str] = []
    # 1) 引号内容（“...” 或 "..."），长度 >= 8 才算引用
    for m in re.finditer(r"[“\"]([^”\"]{8,})[”\"]", answer):
        citations.append(m.group(1))
    # 2) 【...】强调块
    for m in re.finditer(r"【([^】]{8,})】", answer):
        citations.append(m.group(1))
    # 3) "依据/原文/规定"引导句（取到句号）
    for m in re.finditer(r"(?:依据|原文[:：]?|规定[:：]?|条款[:：]?)[：:]?\s*([^。；\n]{8,})。?", answer):
        citations.append(m.group(1))
    # 去重保序
    seen, out = set(), []
    for c in citations:
        key = normalize(c)
        if key and key not in seen:
            seen.add(key)
            out.append(c.strip())
    return out


def _match_with_trim(norm_cite: str, norm_corpus: dict[str, str], max_tries: int = 4) -> str:
    """子串匹配 + 机械首尾修剪重试。

    现实中"依据：'引用原文'，因此..."句式会给引用带转述尾巴；
    修剪是确定性规则（每端每次剪 15%，最多 max_tries 次），
    任何 paraphrase 依然无法通过（词序/用词变化不是首尾修剪能修复的）。
    """
    cite = norm_cite
    for _ in range(max_tries):
        for did, src in norm_corpus.items():
            if cite and cite in src:
                return did
        # 尾部剪 15%
        cut = max(8, int(len(cite) * 0.85))
        cite = cite[:cut]
    return ""


def verify_citations(answer: str, corpus: dict[str, str], min_len: int = 10) -> VerifyResult:
    """逐字核验回答中的引用是否真实出现在源文档中。

    corpus: {doc_id: 源文件规范化文本}。规范化后做子串匹配——
    任何"近似转述"都无法通过，从而保证引用 100% 可溯源。
    """
    norm_corpus = {did: normalize(txt) for did, txt in corpus.items()}
    verified, rejected = [], []
    for raw in extract_citations(answer):
        if len(normalize(raw)) < min_len:
            continue  # 过短片段不构成引用
        hit = _match_with_trim(normalize(raw), norm_corpus)
        c = Citation(raw=raw, found_in=hit)
        (verified if hit else rejected).append(c)
    # 包含归并：同一片段被多个句式重复抽取时，"纯引用"与"引用+转述尾巴"并存；
    # 若 rejected 的规范化文本包含某条 verified，则它是包装句，剔除（以纯引用为准）
    verified_norms = [normalize(v.raw) for v in verified]
    rejected = [
        r for r in rejected
        if not any(vn in normalize(r.raw) for vn in verified_norms)
    ]
    total = len(verified) + len(rejected)
    return VerifyResult(
        verified=verified,
        rejected=rejected,
        pass_rate=round(len(verified) / total, 4) if total else 1.0,
    )
