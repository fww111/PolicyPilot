"""第 1 周试爬 v3：苏州市政府规范性文件库（静态渲染，验证可抓）。

数据源结论（试爬验证记录，写进初赛文档"原始数据说明"）：
  - www.gov.cn 列表/详情页均 JS 动态渲染，静态抓取不可行（接口仅给元数据）
  - 深圳政府门户 TLS 为国密/特殊曲线，Python httpx 无法握手
  - 苏州市政府 www.suzhou.gov.cn 规范性文件库静态渲染，可用 ← 本脚本
用法：cd PolicyPilot && uv run python scripts/trial_crawl.py [数量]
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
BASE = "https://www.suzhou.gov.cn/szsrmzf/gfxwj/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PolicyPilot-Research/0.1 (student competition)"}
DELAY = 2.0
TITLE_WORDS = ("办法", "条例", "措施", "意见", "规定", "细则", "方案", "政策", "补贴", "资金", "扶持")


def collect_links(client: httpx.Client, need: int) -> list[str]:
    """列表页翻页收集规范性文件详情链接。"""
    urls: list[str] = []
    page_url: str | None = BASE
    while page_url and len(urls) < need + 20:
        time.sleep(DELAY)
        try:
            resp = client.get(page_url)
            resp.raise_for_status()
            resp.encoding = resp.charset_encoding or "utf-8"
        except Exception as e:
            print(f"  [warn] 列表页失败 {page_url}: {e}")
            break
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select("a[href$='.shtml']"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if len(title) > 10 and any(w in title for w in TITLE_WORDS) and "gfxwj" not in href:
                full = urljoin(page_url, href)
                if full not in urls:
                    urls.append(full)
        print(f"  {page_url} -> 累计 {len(urls)} 条")
        # 翻页：找"下页"或 index_N.shtml 模式
        nxt = None
        for a in soup.select("a"):
            if a.get_text(strip=True) in ("下页", "下一页", "»", ">"):
                nxt = urljoin(page_url, a.get("href", ""))
                break
        m = re.search(r"index_(\d+)\.shtml", page_url)
        if not nxt and m:
            nxt = re.sub(r"index_\d+\.shtml", f"index_{int(m.group(1)) + 1}.shtml", page_url)
        page_url = nxt
    return urls


def save_policy(client: httpx.Client, url: str) -> Path | None:
    try:
        time.sleep(DELAY)
        resp = client.get(url)
        resp.raise_for_status()
        resp.encoding = resp.charset_encoding or "utf-8"
    except Exception as e:
        print(f"  [warn] 详情页失败 {url}: {e}")
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    title = (soup.select_one("h1") or soup.select_one("title"))
    title_text = title.get_text(strip=True) if title else url.rsplit("/", 1)[-1]
    safe = re.sub(r'[\\/:*?"<>|〔〕\s]+', "_", title_text.split("_")[0])[:44]
    dest = RAW_DIR / f"sz_{safe}.html"
    dest.write_text(resp.text, encoding="utf-8")
    return dest


def main(target: int = 30) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True, trust_env=False) as client:
        links = collect_links(client, target)
        print(f"共收集 {len(links)} 条规范性文件链接，目标下载 {target} 份")
        saved = 0
        for url in links:
            if saved >= target:
                break
            dest = save_policy(client, url)
            if dest:
                saved += 1
                print(f"  [{saved:02d}/{target}] {dest.stem[:46]}")
        print(f"完成：{saved} 份已存入 {RAW_DIR}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
