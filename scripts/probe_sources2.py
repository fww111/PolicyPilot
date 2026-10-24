"""探测：1) gov.cn政策壳页面的PDF附件 2) 江苏省政府政策库真实入口。"""
import re

import httpx
from bs4 import BeautifulSoup

headers = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1"}
with httpx.Client(headers=headers, timeout=20, follow_redirects=True, trust_env=False) as c:
    # 1) gov.cn 壳页面找附件
    shell = "https://www.gov.cn/zhengce/zhengceku/202610/content_7082738.htm"
    r = c.get(shell)
    r.encoding = r.charset_encoding or "utf-8"
    pdfs = re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text, re.I)
    print("gov.cn壳页面PDF附件:", pdfs[:5] if pdfs else "无")
    # 找页面里的附件区线索
    m = re.findall(r'(?:附件|下载|原文)[^<>]{0,50}', r.text)
    print("附件区线索:", list(dict.fromkeys(m))[:5])

    # 2) 江苏省政府：从首页找政策文件库真实链接
    r2 = c.get("https://www.gd.gov.cn/")
    r2.encoding = r2.charset_encoding or "utf-8"
    soup = BeautifulSoup(r2.text, "lxml")
    print("\n广东省首页状态:", r2.status_code)
    for a in soup.select("a[href]"):
        t = a.get_text(strip=True)
        if any(k in t for k in ("政策文件", "政府规章", "规范性文件", "政策库")):
            print(f"  [{t}] -> {a['href'][:80]}")
