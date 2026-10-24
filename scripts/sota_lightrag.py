"""SOTA 基线对比：LightRAG（港大）接入统一评测协议。

科研对比设计（docs/07）：
  - 同一语料（苏州+江苏政策全文）、同一评测集（PolicyBench）、同一指标
  - LightRAG 用 mix 模式（local+global 双层检索，其论文的最强配置）
  - 智谱 glm-5.3-flash 做抽取与生成（与我们的系统同一 LLM，控制变量）

用法：
  建索引（耗时，后台跑）：uv run python scripts/sota_lightrag.py index
  打分：                  uv run python scripts/sota_lightrag.py eval
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import os  # noqa: E402

WORK_DIR = ROOT / "data" / "lightrag_index"


def build_llm_func():
    """智谱 API 包装（LightRAG 要求 async 函数）。"""
    from policy_pilot.extraction.triple_extractor import get_client

    client = get_client()

    async def llm_func(prompt: str, **kwargs) -> str:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=os.getenv("LLM_EXTRACT_MODEL", "glm-5.3-flash"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            extra_body={"thinking": {"level": "low"}},
        )
        return resp.choices[0].message.content or ""

    return llm_func


def build_embedding_func():
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
    )

    async def embedding_func(texts: list[str]) -> list[list[float]]:
        resp = await asyncio.to_thread(
            client.embeddings.create, model="embedding-3", input=texts
        )
        return [d.embedding for d in resp.data]

    return embedding_func


async def do_index(limit: int = 0) -> None:
    from lightrag import LightRAG
    from lightrag.llm.openai import openai_complete_if_cache
    from lightrag.utils import EmbeddingFunc

    rag = LightRAG(
        working_dir=str(WORK_DIR),
        llm_model_func=lambda prompt, **kw: openai_complete_if_cache(
            os.getenv("LLM_EXTRACT_MODEL", "glm-5.3-flash"),
            prompt,
            api_key=os.getenv("LLM_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),
            **{k: v for k, v in kw.items() if k != "hashing_kv"},
        ),
        embedding_func=EmbeddingFunc(
            embedding_dim=2048,
            func=lambda texts: asyncio.to_thread(_zhipu_embed, texts),
        ),
    )
    await rag.initialize_storages()
    corpus = load_corpus()
    if limit:
        corpus = dict(list(corpus.items())[:limit])
    print(f"语料 {len(corpus)} 份，开始 LightRAG 索引（实体抽取，耗时较长）...")
    for i, (name, text) in enumerate(corpus.items(), 1):
        await rag.ainsert(text[:8000])  # 截断防超长
        print(f"  [{i}/{len(corpus)}] {name[:36]}")
    print("索引完成 ->", WORK_DIR)


def _zhipu_embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL"),
    )
    resp = client.embeddings.create(model="embedding-3", input=texts)
    import numpy as np
    return np.array([d.embedding for d in resp.data])


def load_corpus() -> dict[str, str]:
    from policy_pilot.parser.doc_parser import parse_any

    corpus = {}
    for pattern in ("sz_*.html", "js_*.html"):
        for f in (ROOT / "data/raw").glob(pattern):
            doc = parse_any(f)
            if len(doc.full_text) > 400:
                corpus[f.stem[:40]] = doc.full_text
    return corpus


async def do_eval(limit: int = 0) -> None:
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc

    rag = LightRAG(
        working_dir=str(WORK_DIR),
        llm_model_func=build_llm_func(),
        embedding_func=EmbeddingFunc(embedding_dim=2048, func=lambda texts: asyncio.to_thread(_zhipu_embed, texts)),
    )
    await rag.initialize_storages()
    bench = json.loads((ROOT / "data/eval/benchmark.json").read_text(encoding="utf-8"))
    items = [x for x in bench if x["q_type"] in ("multi_hop", "validity", "conflict")]
    if limit:
        items = items[:limit]
    print(f"评测 {len(items)} 题（LightRAG mix 模式）")
    rows = []
    for i, it in enumerate(items, 1):
        try:
            result = await rag.aquery(it["question"], param=QueryParam(mode="mix", only_need_context=False))
            rows.append({"item_id": it["item_id"], "q_type": it["q_type"], "gold_ids": it.get("gold_ids", []),
                         "gold_answer": it["gold_answer"], "answer": str(result)[:2000]})
            print(f"  [{i}/{len(items)}] {it['item_id']} 完成")
        except Exception as e:
            rows.append({"item_id": it["item_id"], "error": f"{type(e).__name__}: {str(e)[:80]}"})
            print(f"  [{i}] 失败: {type(e).__name__}")
    out = ROOT / "data/eval/sota_lightrag_results.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果 -> {out.name}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "index"
    if mode == "index":
        asyncio.run(do_index(int(sys.argv[2]) if len(sys.argv) > 2 else 30))
    elif mode == "eval":
        asyncio.run(do_eval(int(sys.argv[2]) if len(sys.argv) > 2 else 0))
