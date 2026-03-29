#!/usr/bin/env python3
"""
小红书 AI 日报 — 报告生成器（Mac Mini 端）
接收爬取好的 JSON 数据，执行 GLM 分类 + 报告格式化 + 飞书推送。
不负责爬取，数据由本地 MacBook 推送过来。

用法：
  python3 xhs_report.py /path/to/scraped.json          # 从文件读取
  cat scraped.json | python3 xhs_report.py -            # 从 stdin 读取
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────
FEISHU_APP_ID     = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_USER_ID    = os.environ.get("FEISHU_USER_ID", "")

ARK_API_KEY  = os.environ.get("ARK_API_KEY", "")
ARK_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
ARK_MODEL    = os.environ.get("ARK_MODEL", "glm-4.7")
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SECRETS_FILE = os.path.join(SCRIPT_DIR, "secrets.env")

AI_KEYWORDS = [
    "ai", "大模型", "claude", "gpt", "llm", "agent", "grok",
    "vibe coding", "openclaw", "gemini", "多模态", "深度学习",
    "机器学习", "神经网络", "prompt", "rag", "sora", "midjourney",
    "runway", "cursor", "copilot", "manus", "openai", "anthropic",
    "智能体", "模型", "推理",
]

TREND_KEYWORDS = ["Claude", "Agent", "Vibe Coding", "大模型", "AI", "OpenClaw",
                  "GPT", "多模态", "Cursor", "Manus"]


def load_secrets():
    """从 secrets.env 加载密钥（不覆盖已有环境变量）"""
    global FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID, ARK_API_KEY
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not os.environ.get(key):
                    os.environ[key] = value

    FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
    FEISHU_USER_ID = os.environ.get("FEISHU_USER_ID", "")
    ARK_API_KEY = os.environ.get("ARK_API_KEY", "")


def check_secrets() -> bool:
    missing = []
    if not FEISHU_APP_ID:
        missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET:
        missing.append("FEISHU_APP_SECRET")
    if not FEISHU_USER_ID:
        missing.append("FEISHU_USER_ID")
    if not ARK_API_KEY:
        missing.append("ARK_API_KEY")
    if missing:
        print(f"❌ 缺少密钥: {', '.join(missing)}", file=sys.stderr)
        print(f"请在 {SECRETS_FILE} 或环境变量中配置。", file=sys.stderr)
        return False
    return True


# ── GLM API ──────────────────────────────────────────
_glm_client = None

def get_glm_client():
    global _glm_client
    if _glm_client is None:
        from openai import OpenAI as _OpenAI
        _glm_client = _OpenAI(
            api_key=ARK_API_KEY, base_url=ARK_BASE_URL,
            timeout=60.0,
        )
    return _glm_client


def call_glm(prompt: str, max_tokens: int = 200) -> str:
    client = get_glm_client()
    resp = client.chat.completions.create(
        model=ARK_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


# ── 内容处理 ─────────────────────────────────────────
def pre_filter(notes: list) -> list:
    return [n for n in notes if any(kw in n.get("title", "").lower() for kw in AI_KEYWORDS)]


def classify_one(item: dict) -> str:
    try:
        likes_str = item.get("likes", "0").replace(",", "").replace("w", "0000").replace("万", "0000")
        likes = int(likes_str) if likes_str.isdigit() else 0
    except Exception:
        likes = 0

    prompt = (
        f"小红书帖子标题:「{item['title']}」点赞:{item.get('likes','0')}\n"
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
            return ""
        c = int(m.group())
        if c == 0:
            return ""
        cat = {1: "a1", 2: "a2", 3: "a3"}.get(c, "")
        if cat == "a3" and likes < 500:
            return ""
        return cat
    except Exception:
        return ""


def summarize_one(title: str) -> str:
    try:
        return call_glm(
            f"小红书帖子标题:「{title}」\n用15字内概括核心价值，直接输出文字，不要引号。",
            max_tokens=30
        ).strip().strip('"').strip("'")
    except Exception:
        return ""


def build_report_data(notes: list) -> dict:
    a1, a2, a3, trends = [], [], [], []
    print(f"  逐条分类 {len(notes)} 条...", file=sys.stderr)

    for idx, item in enumerate(notes):
        cat = classify_one(item)
        if cat == "a1":
            a1.append(item)
        elif cat == "a2":
            a2.append(item)
        elif cat == "a3":
            a3.append(item)
        for kw in TREND_KEYWORDS:
            if kw.lower() in item["title"].lower() and kw not in trends:
                trends.append(kw)
        if (idx + 1) % 20 == 0:
            print(f"  进度 {idx+1}/{len(notes)}: a1={len(a1)} a2={len(a2)} a3={len(a3)}", file=sys.stderr)

    def top5(items):
        seen, out = set(), []
        for item in items:
            k = item.get("id", "")
            if k and k not in seen:
                seen.add(k)
                out.append(item)
        return out[:5]

    selected = {"a1": top5(a1), "a2": top5(a2), "a3": top5(a3)}
    total = sum(len(v) for v in selected.values())
    if total > 0:
        print(f"  为 {total} 条精选笔记生成摘要...", file=sys.stderr)
    for key in ["a1", "a2", "a3"]:
        for item in selected[key]:
            item["summary"] = summarize_one(item["title"])

    trend_summary = "AI内容持续活跃"
    if a1 or a2 or a3:
        try:
            trend_summary = call_glm(
                f"今日小红书AI热词{trends[:6]}，用一句话概括AI风向（12字内）：",
                max_tokens=30
            ).strip().strip('"').strip("'")
        except Exception:
            pass

    return {
        "a1": selected["a1"], "a2": selected["a2"], "a3": selected["a3"],
        "a4": {"trends": trends[:10], "summary": trend_summary},
    }


def format_report(data: dict, date_str: str) -> str:
    lines = [f"📱 小红书 AI 日报 · {date_str}", "=" * 35, ""]

    def fmt(item, idx):
        url = f"https://www.xiaohongshu.com/explore/{item.get('id', '')}"
        summary = item.get("summary", "")
        line = f"  {idx}. 【{item.get('author','')}】{item.get('title','')}"
        if summary:
            line += f"\n     💬 {summary}"
        line += f"\n     👍{item.get('likes','0')}  🔗 {url}"
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
    lines.append("—— 由 GLM-4.7 + bb-browser 自动生成 ——")
    return "\n".join(lines)


# ── 飞书推送 ─────────────────────────────────────────
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
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise RuntimeError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET 环境变量")
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


# ── 主流程 ────────────────────────────────────────────
def main():
    load_secrets()
    if not check_secrets():
        sys.exit(1)

    if len(sys.argv) < 2:
        print("用法: python3 xhs_report.py <scraped.json | ->", file=sys.stderr)
        sys.exit(1)

    source = sys.argv[1]
    if source == "-":
        raw = sys.stdin.read()
    else:
        with open(source) as f:
            raw = f.read()

    data = json.loads(raw)
    notes = data.get("notes", data) if isinstance(data, dict) else data
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d %H:%M")) if isinstance(data, dict) else datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"[{date_str}] 收到 {len(notes)} 条原始数据", file=sys.stderr)

    filtered = pre_filter(notes)
    print(f"  AI关键词过滤后 {len(filtered)} 条", file=sys.stderr)

    report_data = build_report_data(filtered)
    report = format_report(report_data, date_str)
    print("\n" + report, file=sys.stderr)

    print("\n发送飞书通知...", file=sys.stderr)
    try:
        token = get_feishu_token()
        send_feishu_message(token, report)
        print("✅ 飞书推送成功", file=sys.stderr)
    except Exception as e:
        print(f"[飞书推送失败] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
