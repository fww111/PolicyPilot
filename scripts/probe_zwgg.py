"""定向补抓探测：苏州政务公告按日期目录 + 委办局政策源。"""
from bs4 import BeautifulSoup
import httpx

headers = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1"}
candidates = [
    # 政务公告按月目录（从详情页 URL 模式 /szsrmzf/zwgg/202610/xxx.shtml 反推）
    "https://www.suzhou.gov.cn/szsrmzf/zwgg/202610/",
    "https://www.suzhou.gov.cn/szsrmzf/zwgg/202609/",
    # 政府公报
    "https://www.suzhou.gov.cn/szsrmzf/zwgk/zfgb/",
]
with httpx.Client(headers=headers, timeout=15, follow_redirects=True, trust_env=False) as c:
    for url in candidates:
        try:
            r = c.get(url)
            r.encoding = r.charset_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "lxml")
            title = (soup.title.get_text(strip=True) if soup.title else "?")[:26]
            links = [
                a.get_text(strip=True)
                for a in soup.select("a[href$='.shtml']")
                if len(a.get_text(strip=True)) > 10
                and any(w in a.get_text(strip=True) for w in ("办法", "措施", "意见", "规定", "细则", "方案", "条例", "目录", "资金", "补贴"))
                and "解读" not in a.get_text(strip=True)
                and "征求" not in a.get_text(strip=True)
            ]
            is_home = title == "苏州市人民政府"
            print(f"{url}\n  {r.status_code} | {'疑似首页' if is_home else title} | 高质量政策链接: {len(links)}")
            for t in links[:4]:
                print("   ", t[:44])
        except Exception as e:
            print(f"{url} -> {type(e).__name__}")
