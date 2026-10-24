"""江苏省政府政策全文爬虫（定向补抓主力，W3 数据任务）。

发现记录：江苏详情页静态渲染（4877字正文+索引号/分类/机构/日期元数据），
列表页 JS 渲染。策略：首页种子 + 详情页滚雪球 + JCMS dataproxy 接口尝试。

用法：uv run python scripts/crawl_jiangsu.py [目标份数，默认60]
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = "https://www.jiangsu.gov.cn/"
HEADERS = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1 (student competition)"}
# ===== 数据源配置（迁移演示：换城市/栏目只改这里 —— docs/08 创新E）=====
SOURCE_CONFIG = {
    "columnid": "46144",  # 省政府办公室(厅)文件；迁移示例：84242=最新文件栏目
    "unitid": "356383",
    "webname": "jsc",
    "base": "https://www.jiangsu.gov.cn/",
}
POLICY_WORDS = ("措施", "办法", "意见", "规定", "细则", "条例", "方案", "通知", "决定", "目录")
EXCLUDE = ("解读", "征求", "图解", "新闻发布会", "访谈", "问答", "说明会")
DELAY = 2.0


def extract_body(soup: BeautifulSoup) -> str:
    best, score = "", 0
    for d in soup.find_all(["div", "article", "td"]):
        links = max(len(d.find_all("a")), 1)
        t = d.get_text(strip=True)
        s = len(t) / links
        if len(t) > 500 and s > score:
            best, score = t, s
    return best


def extract_meta(soup: BeautifulSoup) -> dict:
    """江苏详情页自带的结构化元数据（索引号/分类/机构/日期）。"""
    text = soup.get_text(" ", strip=True)
    meta = {}
    for key, pat in [
        ("index_no", r"索引号[：:]\s*(\S+)"),
        ("classify", r"分\s*类[：:]\s*(\S+)"),
        ("puborg", r"发布机构[：:]\s*(\S+)"),
        ("pubdate", r"发文日期[：:]\s*(\S+)"),
        ("docno", r"文\s*号[：:]\s*(\S+)"),
    ]:
        m = re.search(pat, text)
        if m:
            meta[key] = m.group(1)[:60]
    return meta


def main(target: int = 60) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    have = {f.name for f in RAW.glob("js_*.html")}
    client = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True, trust_env=False)

    # 种子：江苏首页政策链接
    r = client.get(BASE)
    r.encoding = r.charset_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "lxml")
    queue: list[str] = []
    for a in soup.select("a[href]"):
        t, h = a.get_text(strip=True), a.get("href", "")
        if "/art/" in h and len(t) > 10 and any(w in t for w in POLICY_WORDS) and not any(x in t for x in EXCLUDE):
            queue.append(urljoin(BASE, h))
    print(f"首页种子 {len(queue)} 条")

    # JCMS dataproxy 全量列表（已验证：col46144 省政府文件库共 5238 条/53 页）
    try:
        for page in range(1, 15):  # 前14页约140条近期文件
            time.sleep(1.5)
            r3 = client.get(
                urljoin(BASE, "module/web/jpage/dataproxy.jsp"),
                params={"page": str(page), "appid": "1", "webid": "1", "path": "/",
                        "columnid": SOURCE_CONFIG["columnid"], "unitid": SOURCE_CONFIG["unitid"], "webname": SOURCE_CONFIG["webname"],
                        "permissiontype": "0"},
            )
            r3.encoding = r3.charset_encoding or "utf-8"
            hrefs = re.findall(
                r'<a href="(https?://[^"\s]+/art/[\d/]+/art_\d+_\d+\.s?html)"[^>]*?title="([^"]{6,80})"',
                r3.text,
                re.S,
            )
            if not hrefs:
                break
            for h, t in hrefs:
                if not any(x in t for x in EXCLUDE):
                    queue.append(h)
            print(f"  dataproxy 第{page}页: +{len(hrefs)} 条（队列 {len(queue)}）")
    except Exception as e:
        print(f"dataproxy 尝试失败: {type(e).__name__}")

    seen: set[str] = set()
    saved = 0
    while queue and saved < target:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        time.sleep(DELAY)
        try:
            resp = client.get(url)
            resp.raise_for_status()
            resp.encoding = resp.charset_encoding or "utf-8"
        except Exception as e:
            continue
        s = BeautifulSoup(resp.text, "lxml")
        title = (s.select_one("h1") or s.select_one("title"))
        title_text = title.get_text(strip=True) if title else url[-20:]
        if any(x in title_text for x in EXCLUDE):
            continue
        body = extract_body(s)
        if len(body) < 500:
            continue
        meta = extract_meta(s)
        safe = re.sub(r'[\\/:*?"<>|〔〕\s]+', "_", title_text.split("_")[0])[:44]
        fname = f"js_{safe}.html"
        if fname in have:
            continue
        # 元数据随文件保存（头部注释供解析层用）
        head = f"<!--PPMETA {__import__('json').dumps(meta, ensure_ascii=False)}-->"
        (RAW / fname).write_text(head + resp.text, encoding="utf-8")
        have.add(fname)
        saved += 1
        print(f"  [{saved:02d}/{target}] {safe[:40]} | {meta.get('docno','')[:18]} | {len(body)}字")
        # 滚雪球：本页的政策链接入队
        for a in s.select("a[href*='/art/']"):
            h = urljoin(url, a.get("href", ""))
            if h not in seen:
                queue.append(h)
    print(f"完成：江苏全文新增 {saved} 份，队列剩余 {len(queue)}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
