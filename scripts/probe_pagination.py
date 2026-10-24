"""探测苏州政策文件库的翻页机制。"""
import re

import httpx

headers = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1"}
with httpx.Client(headers=headers, timeout=20, follow_redirects=True, trust_env=False) as c:
    r = c.get("https://www.suzhou.gov.cn/szsrmzf/gfxwj/")
    r.encoding = r.charset_encoding or "utf-8"
    html = r.text

print("页面长度:", len(html))
for pat, name in [
    (r"createListHTML[^\"\']{0,60}", "createListHTML"),
    (r"location\.href[^;]{0,80}", "翻页跳转"),
    (r"[?&](?:PN|pn|page|Page|pageIndex)\s*[=:]\s*\d+", "分页参数"),
    (r"totalpage|totalCount|recordcount|pagecount", "总页数变量"),
    (r"index_\d+\.shtml", "静态分页文件"),
]:
    hits = re.findall(pat, html, re.I)
    if hits:
        print(f"[{name}]", list(dict.fromkeys(hits))[:4])

for m in re.findall(r"var\s+\w+\s*=\s*[^;\n]{5,90}", html)[:10]:
    print("JS:", m[:100])

# 页面上的分页区域HTML
m = re.search(r'<div[^>]*class="[^"]*(?:page|pagination|fenye)[^"]*"[^>]*>.{0,500}', html, re.I | re.S)
if m:
    print("分页区:", re.sub(r"\s+", " ", m.group(0))[:300])
