#!/usr/bin/env python3.11
"""
小红书 AI 日报生成器
每日从小红书抓取 AI 相关内容，精选后通过飞书推送
"""

import json
import subprocess
import os
import re
import sys
import urllib.request
from datetime import datetime

from openai import OpenAI as _OpenAI

# ── 配置 ──────────────────────────────────────────────
FEISHU_APP_ID     = os.environ.get("FEISHU_APP_ID", "cli_redacted_legacy_app_id")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "feishu_secret_redacted")
FEISHU_USER_ID    = os.environ.get("FEISHU_USER_ID", "ou_91dca3ed6fc58b46a17b214cdffc7fc7")
# 火山引擎方舟 GLM-4.7（兼容 OpenAI SDK）
ARK_API_KEY       = os.environ.get("ARK_API_KEY", "[REDACTED_ARK_API_KEY]")
ARK_BASE_URL      = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL         = "glm-4-7-251222"
MCPORTER_TIMEOUT  = 90000
SEARCH_TIMEOUT    = 12000           # 搜索快速超时，失败直接跳过
MCPORTER_CONFIG   = os.path.expanduser("~/.claude/skills/config/mcporter.json")

SEARCH_KEYWORDS = ["AI工具", "Claude", "大模型", "Agent", "Vibe Coding", "OpenClaw"]

AI_KEYWORDS = [
    "ai", "大模型", "claude", "gpt", "llm", "agent", "grok",
    "vibe coding", "openclaw", "gemini", "多模态", "深度学习",
    "机器学习", "神经网络", "prompt", "rag", "sora", "midjourney",
    "runway", "cursor", "copilot", "manus", "openai", "anthropic",
    "智能体", "模型", "推理",
]

TREND_KEYWORDS = ["Claude", "Agent", "Vibe Coding", "大模型", "AI", "OpenClaw", "GPT", "多模态", "Cursor", "Manus"]


# ── GLM API（火山引擎方舟，兼容 OpenAI SDK）─────────────
_glm_client = None

def get_glm_client():
    global _glm_client
    if _glm_client is None:
        _glm_client = _OpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    return _glm_client


def call_glm(prompt: str, max_tokens: int = 200) -> str:
    """调用 GLM-4.7，返回文本"""
    client = get_glm_client()
    resp = client.chat.completions.create(
        model=ARK_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


# ── mcporter ─────────────────────────────────────────
def mcporter_call(tool_call: str, timeout_ms: int = MCPORTER_TIMEOUT):
    try:
        result = subprocess.run(
            ["mcporter", "--config", MCPORTER_CONFIG, "call", tool_call, "--timeout", str(timeout_ms)],
            capture_output=True, text=True, timeout=timeout_ms // 1000 + 10
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        print(f"[mcporter error] {tool_call[:50]}: {result.stderr[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[mcporter exception] {e}", file=sys.stderr)
        return None


# ── 飞书 ──────────────────────────────────────────────
def feishu_request(path: str, payload: dict, token: str = None) -> dict:
    url = f"https://open.feishu.cn/open-apis{path}"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_feishu_token() -> str:
    resp = feishu_request("/auth/v3/tenant_access_token/internal", {
        "app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET
    })
    return resp.get("tenant_access_token", "")


def send_feishu_message(token: str, text: str):
    feishu_request("/im/v1/messages?receive_id_type=open_id", {
        "receive_id": FEISHU_USER_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }, token)


# ── 内容处理 ──────────────────────────────────────────
def pre_filter(feeds: list) -> list:
    """关键词快速预过滤"""
    result = []
    for f in feeds:
        title = f.get("noteCard", {}).get("displayTitle", "").lower()
        if title and any(kw in title for kw in AI_KEYWORDS):
            result.append(f)
    return result


def classify_one(item: dict) -> dict:
    """单条帖子分类，只返回单个数字"""
    try:
        likes = int(str(item['l']).replace(',', '').replace('w', '0000') or '0')
    except Exception:
        likes = 0

    prompt = (
        f"小红书帖子标题:「{item['t']}」点赞:{item['l']}\n"
        "请分类（只返回1个数字）:\n"
        "0=不是AI相关内容\n"
        "1=AI前沿研究/论文/评测/多模态\n"
        "2=AI产品体验/工具推荐/新品发布\n"
        "3=AI实践分享/使用心得/workflow\n"
        "只返回数字0/1/2/3，不要任何其他内容。"
    )
    try:
        raw = call_glm(prompt, max_tokens=5).strip()
        m = re.search(r'[0-3]', raw)
        if not m:
            return {}
        c = int(m.group())
        if c == 0:
            return {}
        cat = {1: "a1", 2: "a2", 3: "a3"}.get(c, "")
        if cat == "a3" and likes < 500:
            return {}
        return {"c": cat}
    except Exception:
        return {}


def summarize_one(title: str) -> str:
    """用 GLM 对帖子标题生成一句话摘要（15字内）"""
    try:
        return call_glm(
            f"小红书帖子标题:「{title}」\n用15字内概括这篇帖子的核心价值，直接输出文字，不要引号。",
            max_tokens=30
        ).strip().strip('"').strip("'")
    except Exception:
        return ""


def build_report_data(feeds: list) -> dict:
    """逐条分类，精选后补充摘要"""
    simplified = []
    for f in feeds:
        nc = f.get("noteCard", {})
        ii = nc.get("interactInfo", {})
        title = nc.get("displayTitle", "").strip()
        if not title:
            continue
        # 小红书帖子链接格式
        feed_id = f.get("id", "")
        xsec_token = f.get("xsecToken", "")
        url = f"https://www.xiaohongshu.com/explore/{feed_id}" if feed_id else ""
        simplified.append({
            "i": feed_id,
            "t": title,
            "a": nc.get("user", {}).get("nickname", ""),
            "l": ii.get("likedCount", "0"),
            "u": url,
        })

    a1, a2, a3, trends = [], [], [], []
    print(f"  逐条分类 {len(simplified)} 条...")

    for idx, item in enumerate(simplified):
        res = classify_one(item)
        c = res.get("c", "")
        if c == "a1":
            a1.append(item)
        elif c == "a2":
            a2.append(item)
        elif c == "a3":
            a3.append(item)
        # 提取趋势词
        for kw in TREND_KEYWORDS:
            if kw.lower() in item["t"].lower() and kw not in trends:
                trends.append(kw)
        if (idx + 1) % 20 == 0:
            print(f"  进度 {idx+1}/{len(simplified)}: a1={len(a1)} a2={len(a2)} a3={len(a3)}")

    def top5(items):
        seen, out = set(), []
        for item in items:
            k = item.get("i", "")
            if k and k not in seen:
                seen.add(k)
                out.append(item)
        return out[:5]

    # 对精选帖子补充摘要
    selected = {"a1": top5(a1), "a2": top5(a2), "a3": top5(a3)}
    total = sum(len(v) for v in selected.values())
    if total > 0:
        print(f"  为 {total} 条精选帖子生成摘要...")
    for key in ["a1", "a2", "a3"]:
        for item in selected[key]:
            item["s"] = summarize_one(item["t"])

    summary = "AI内容持续活跃"
    if a1 or a2 or a3:
        try:
            summary = call_glm(
                f"今日小红书AI热词{trends[:6]}，用一句话概括AI风向（12字内）：",
                max_tokens=30
            ).strip().strip('"').strip("'")
        except Exception:
            pass

    return {
        "a1": selected["a1"], "a2": selected["a2"], "a3": selected["a3"],
        "a4": {"trends": trends[:10], "summary": summary},
    }


def format_report(data: dict, date_str: str) -> str:
    lines = [f"📱 小红书 AI 日报 · {date_str}", "=" * 35, ""]

    def fmt(item, idx):
        url = item.get("u", "")
        summary = item.get("s", "")
        line = f"  {idx}. 【{item.get('a','')}】{item.get('t','')}"
        if summary:
            line += f"\n     💬 {summary}"
        line += f"\n     👍{item.get('l','0')}"
        if url:
            line += f"  🔗 {url}"
        return line

    for key, emoji, label in [("a1","🔬","A1｜前沿研究"), ("a2","🛠","A2｜产品体验"), ("a3","💡","A3｜实践分享")]:
        items = data.get(key, [])
        if items:
            lines.append(f"{emoji} {label}")
            for i, item in enumerate(items, 1):
                lines.append(fmt(item, i))
            lines.append("")

    a4 = data.get("a4", {})
    trends = a4.get("trends", [])
    summary = a4.get("summary", "")
    lines.append("🔥 A4｜今日趋势")
    if trends:
        lines.append("  热词: " + " · ".join(f"#{t}" for t in trends[:8]))
    if summary:
        lines.append(f"  风向: {summary}")
    lines.append("")
    lines.append("—— 由 GLM-4.7 + 小红书 MCP 自动生成 ——")
    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────
def main():
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{date_str}] 开始抓取小红书内容...")

    all_feeds, seen_ids = [], set()
    search_failed = 0

    print("  → 抓取首页关注流...")
    home = mcporter_call("xiaohongshu.list_feeds()")
    if home:
        for f in home.get("feeds", []):
            fid = f.get("id", "")
            if fid and fid not in seen_ids:
                seen_ids.add(fid)
                all_feeds.append(f)
    print(f"     得到 {len(all_feeds)} 条")

    for kw in SEARCH_KEYWORDS:
        print(f"  → 搜索「{kw}」...", end=" ", flush=True)
        res = mcporter_call(f'xiaohongshu.search_feeds(keyword: "{kw}")', timeout_ms=SEARCH_TIMEOUT)
        if res:
            added = 0
            for f in res.get("feeds", []):
                fid = f.get("id", "")
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    all_feeds.append(f)
                    added += 1
            print(f"新增 {added} 条")
        else:
            print("超时跳过")
            search_failed += 1

    # 搜索全部失败时飞书告警
    if search_failed == len(SEARCH_KEYWORDS):
        print("⚠️  所有关键词搜索均失败，Cookie 可能已失效")
        try:
            token = get_feishu_token()
            send_feishu_message(token, "⚠️ 小红书 Cookie 已失效，搜索功能不可用，请更新 Cookie。\n（首页流仍可正常推送）")
        except Exception:
            pass

    print(f"\n共收集 {len(all_feeds)} 条，开始筛选...")
    filtered = pre_filter(all_feeds)
    print(f"AI关键词过滤后 {len(filtered)} 条")

    data = build_report_data(filtered)
    report = format_report(data, date_str)
    print("\n" + report)

    print("\n发送飞书通知...")
    try:
        token = get_feishu_token()
        send_feishu_message(token, report)
        print("✅ 飞书推送成功")
    except Exception as e:
        print(f"[飞书推送失败] {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
