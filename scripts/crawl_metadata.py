"""正式数据采集 v2：三层组合策略。

层1 元数据层（本脚本）：gov.cn 政策库公开接口，多关键词翻页采集 300+ 条结构化元数据
    （文号/标题/机关/日期/主题分类/摘要/URL）——直接入本体 Policy 实体，不经 LLM 抽取，
    本身就是"多模态异构数据统一识别"中结构化源的示范。
层2 全文层：苏州静态详情页（crawl_suzhou_daily.py 每日累积）
层3 已有 24 份苏州全文。

用法：uv run python scripts/crawl_metadata.py [目标条数，默认300]
限速 2s/请求，断点续采（已采关键词跳过）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "gov_metadata.jsonl"
API = "https://sousuo.www.gov.cn/search-gov/data"
HEADERS = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1 (student competition)",
           "Referer": "https://sousuo.www.gov.cn/"}

# 惠企政策核心关键词（覆盖资助/税收/融资/创新/行业专项）
KEYWORDS = ["中小企业", "专精特新", "补贴", "税收优惠", "融资", "科技创新", "制造业", "高新技术企业", "营商环境", "产业政策"]
LIBS = ["zhengcelibrary_gw", "zhengcelibrary_bm"]  # 国务院文件 + 部门文件


def load_done() -> dict[str, dict]:
    if OUT.exists():
        return {r["pcode"]: r for r in (json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()) if r.get("pcode")}
    return {}


def main(target: int = 300) -> None:
    done = load_done()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(headers=HEADERS, timeout=25, trust_env=False)
    print(f"已有元数据 {len(done)} 条，目标 {target}")
    newly = 0
    for kw in KEYWORDS:
        if len(done) + newly >= target:
            break
        for lib in LIBS:
            for page in range(1, 6):  # 每词每库最多5页
                if len(done) + newly >= target:
                    break
                time.sleep(2)
                params = {"t": lib, "q": kw, "timetype": "timeqb", "sort": "pubtime",
                          "sortType": "1", "searchfield": "title", "p": str(page), "n": "10"}
                try:
                    data = client.get(API, params=params).json() or {}
                except Exception as e:
                    print(f"  [warn] {kw}/{lib}/p{page}: {type(e).__name__}")
                    time.sleep(10)  # 可能限流，退避
                    continue
                svo = data.get("searchVO") or {}
                items = svo.get("listVO") or []
                if not items:
                    break
                with OUT.open("a", encoding="utf-8") as f:
                    for it in items:
                        pcode = (it.get("pcode") or "").strip()
                        if not pcode or pcode in done:
                            continue
                        rec = {
                            "pcode": pcode, "title": it.get("title", "").replace("<em>", "").replace("</em>", ""),
                            "puborg": it.get("puborg", ""), "pubtime": it.get("pubtimeStr", ""),
                            "theme": it.get("childtype", ""), "summary": it.get("summary", ""),
                            "url": it.get("url", ""), "source": f"gov.cn:{kw}", "lib": lib,
                        }
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        done[pcode] = rec
                        newly += 1
            print(f"  [{kw}] 累计 {len(done)} 条")
    print(f"完成：新增 {newly}，总计 {len(done)} 条 -> {OUT.name}")
    # 统计
    themes: dict[str, int] = {}
    for r in done.values():
        t = (r.get("theme") or "未分类").split("\\")[0]
        themes[t] = themes.get(t, 0) + 1
    top = sorted(themes.items(), key=lambda x: -x[1])[:6]
    print("主题分布:", ", ".join(f"{k}({v})" for k, v in top))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
