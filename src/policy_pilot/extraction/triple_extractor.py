"""
LLM 本体引导抽取器 —— 创新点2（低资源半自动本体构建）的核心。

流程（半自动闭环）：
    政策文本 -> [LLM + ONTOLOGY_PROMPT 约束抽取] -> Triple 候选
    -> confidence >= 阈值 直接入库
    -> confidence <  阈值 进人工复核队列（data/kg/human_review_queue.jsonl）
    -> 人工修正结果回填为 few-shot 示例（越抽越准）

量化记录（写入 docs/03-量化数据记录.md）：
    每批抽取记录：文件数 / token 成本 / 耗时 / 自动通过率 / 人工修正条数
    —— "标注工作量下降 X%" 的原始数据就来自这里，边跑边记，事后补不出来。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from policy_pilot.ontology.policy_ontology import ONTOLOGY_PROMPT, Triple

KG_DIR = Path(__file__).resolve().parents[3] / "data" / "kg"
CONFIDENCE_THRESHOLD = 0.75


class ExtractionResult(BaseModel):
    """单文件抽取结果 + 量化元数据。"""

    file_id: str
    triples: list[Triple] = Field(default_factory=list)
    invalid_items: int = 0
    latency_s: float = 0.0
    usage_tokens: int = 0
    model: str = ""


def get_client() -> OpenAI:
    import os

    return OpenAI(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
    )


def extract_triples(text: str, file_id: str, client: OpenAI | None = None) -> ExtractionResult:
    """对单篇政策文本做本体约束抽取。文本超长时按段落分批（TODO：长文分块策略）。"""
    import os

    client = client or get_client()
    model = os.getenv("LLM_EXTRACT_MODEL", os.getenv("LLM_MODEL", "deepseek-chat"))
    # 智谱等强制思考模型必须指定档位（low/high/max）；设 LLM_THINKING_LEVEL="" 可跳过
    thinking_level = os.getenv("LLM_THINKING_LEVEL", "low")
    extra: dict | None = {"thinking": {"level": thinking_level}} if thinking_level else None
    t0 = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ONTOLOGY_PROMPT},
            {"role": "user", "content": f"抽取以下政策文件的知识三元组：\n\n{text[:12000]}"},
        ],
        temperature=0.0,
        extra_body=extra,
    )
    latency = time.time() - t0
    content = resp.choices[0].message.content or "[]"
    usage = resp.usage.total_tokens if resp.usage else 0

    triples: list[Triple] = []
    invalid = 0
    for item in _load_json_array(content):
        try:
            triples.append(Triple.model_validate(item))
        except ValidationError:
            invalid += 1
    return ExtractionResult(
        file_id=file_id,
        triples=triples,
        invalid_items=invalid,
        latency_s=round(latency, 2),
        usage_tokens=usage,
        model=model,
    )


def split_by_confidence(result: ExtractionResult) -> tuple[list[Triple], list[Triple]]:
    """按置信度分流：自动入库 vs 人工复核。"""
    auto = [t for t in result.triples if t.confidence >= CONFIDENCE_THRESHOLD]
    review = [t for t in result.triples if t.confidence < CONFIDENCE_THRESHOLD]
    return auto, review


def append_review_queue(triples: list[Triple], kg_dir: Path = KG_DIR) -> None:
    kg_dir.mkdir(parents=True, exist_ok=True)
    with (kg_dir / "human_review_queue.jsonl").open("a", encoding="utf-8") as f:
        for t in triples:
            f.write(t.model_dump_json() + "\n")


def _load_json_array(content: str) -> list[dict]:
    """容错解析 LLM 输出（数组或对象均支持）。

    实测 glm-5.3-flash 会在 JSON 前后附加大段说明，且不同任务输出对象
    （{"符合":...}）或数组（[{...}]）形态不一。策略：优先取 ``` 代码块；
    否则做平衡括号扫描提取最外层 JSON；返回 dict 的列表以统一下游接口。
    """
    import re

    content = content.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", content, re.DOTALL)
    if m:
        content = m.group(1)
    data = _extract_balanced_json(content)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _extract_balanced_json(text: str):
    """平衡括号扫描：返回第一个完整的最外层 {...} 或 [...] 解析结果。"""
    for opener, closer in (("{", "}"), ("[", "]")):
        s = text.find(opener)
        if s == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(s, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[s : i + 1])
                    except json.JSONDecodeError:
                        break
    return None
