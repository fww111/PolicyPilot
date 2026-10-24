"""苏州全文每日采集：抓首页及要闻区滚动的政策详情链接，增量下载静态全文。

用法：uv run python scripts/crawl_suzhou_daily.py   （可反复跑，自动去重）
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = "https://www.suzhou.gov.cn/"
HEADERS = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1 (student competition)"}
TITLE_WORDS = ("办法", "条例", "措施", "意见", "规定", "细则", "方案", "补贴", "奖励", "资金", "扶持", "政策")
# 排除 B1 发现的无抽取价值类型
EXCLUDE = ("解读", "征求意见", "反馈", "一图读懂", "图解", "新闻发布会", "报名", "公示公告")


def existing_names() -> set[str]:
    return {f.name for f in RAW.glob("sz_*.html")}


def main() -> None:
    have = existing_names()
    client = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True, trust_env=False)
    client.get(BASE)  # 预热
    time.sleep(1)
    r = client.get(BASE)
    r.encoding = r.charset_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "lxml")
    links: list[str] = []
    for a in soup.select("a[href$='.shtml']"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if (
            len(title) > 10
            and any(w in title for w in TITLE_WORDS)
            and not any(x in title for x in EXCLUDE)
            and "gfxwj" not in href
        ):
            full = urljoin(BASE, href)
            if full not in links:
                links.append(full)
    print(f"首页发现候选政策链接 {len(links)} 条")
    saved = 0
    for url in links:
        time.sleep(2)
        try:
            resp = client.get(url)
            resp.raise_for_status()
            resp.encoding = resp.charset_encoding or "utf-8"
        except Exception as e:
            print(f"  [warn] {url[-40:]}: {type(e).__name__}")
            continue
        s = BeautifulSoup(resp.text, "lxml")
        # 正文有效性检查（.detail-mod 已验证）
        body = s.select_one(".detail-mod") or s.select_one(".container.article")
        if not body or len(body.get_text(strip=True)) < 400:
            continue
        title = (s.select_one("h1") or s.select_one("title")).get_text(strip=True)
        safe = re.sub(r'[\\/:*?"<>|〔〕\s]+', "_", title.split("_")[0])[:44]
        fname = f"sz_{safe}.html"
        if fname in have:
            continue
        (RAW / fname).write_text(resp.text, encoding="utf-8")
        have.add(fname)
        saved += 1
        print(f"  [{saved:02d}] {safe[:40]}")
    print(f"完成：新增全文 {saved} 份，现有全文 {len(have)} 份")


if __name__ == "__main__":
    main()
