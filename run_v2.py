#!/usr/bin/env python3
"""
小红书 AI 日报生成器 v2
用 bb-browser 替代 mcporter/Docker，直接通过 CDP 连接浏览器抓取数据。

用法:
  python3 run_v2.py              # 正常运行：抓取 + 分类 + 飞书推送
  python3 run_v2.py --scrape     # 仅抓取，输出 JSON 到 stdout
  python3 run_v2.py --test       # 测试模式：少量数据 + 推送
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# ── 配置 ──────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 密钥从环境变量加载，不提供硬编码 fallback
# 可通过 secrets.env 或 HEARTBEAT 的 export 注入
FEISHU_APP_ID     = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_USER_ID    = os.environ.get("FEISHU_USER_ID", "")
ARK_API_KEY       = os.environ.get("ARK_API_KEY", "")
ARK_BASE_URL      = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
ARK_MODEL         = os.environ.get("ARK_MODEL", "glm-4-7-251222")

BB_BROWSER = os.environ.get("BB_BROWSER", "bb-browser")

# 密钥配置文件（优先级低于环境变量）
SECRETS_FILE = os.path.join(SCRIPT_DIR, "secrets.env")

# 搜索关键词（精简为 4 个高差异化词）
SEARCH_KEYWORDS = ["AI工具", "Claude", "Vibe Coding", "Agent"]

AI_KEYWORDS = [
    "ai", "大模型", "claude", "gpt", "llm", "agent", "grok",
    "vibe coding", "openclaw", "gemini", "多模态", "深度学习",
    "机器学习", "神经网络", "prompt", "rag", "sora", "midjourney",
    "runway", "cursor", "copilot", "manus", "openai", "anthropic",
    "智能体", "模型", "推理",
]

TREND_KEYWORDS = ["Claude", "Agent", "Vibe Coding", "大模型", "AI", "OpenClaw",
                  "GPT", "多模态", "Cursor", "Manus"]

# 日志文件
LOG_FILE = os.path.join(SCRIPT_DIR, "run.log")

# 去重记录
SEEN_FILE = os.path.join(SCRIPT_DIR, "seen_ids.json")
SEEN_DAYS = 3  # 保留最近 N 天的记录


def load_secrets():
    """从 secrets.env 加载密钥（不覆盖已有环境变量）"""
    global FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID, ARK_API_KEY
    if not os.path.exists(SECRETS_FILE):
        return
    with open(SECRETS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            # 只在环境变量未设置时才加载
            if not os.environ.get(key):
                os.environ[key] = val
    # 重新读取
    FEISHU_APP_ID     = os.environ.get("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
    FEISHU_USER_ID    = os.environ.get("FEISHU_USER_ID", "")
    ARK_API_KEY       = os.environ.get("ARK_API_KEY", "")


def log(msg: str):
    """同时输出到 stderr 和日志文件"""
    print(msg, file=sys.stderr)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def check_secrets():
    """检查必要密钥是否配置"""
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
        log(f"⚠️  缺少配置: {', '.join(missing)}")
        log(f"   请设置环境变量或编辑 {SECRETS_FILE}")
        return False
    return True


# ── 跨天去重 ─────────────────────────────────────────
def load_seen_ids() -> dict:
    """加载已推送过的 note_id 记录 {date_str: [ids]}"""
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen_ids(seen: dict):
    """保存去重记录，清理过期数据"""
    cutoff = (datetime.now() - timedelta(days=SEEN_DAYS)).strftime("%Y-%m-%d")
    cleaned = {k: v for k, v in seen.items() if k >= cutoff}
    with open(SEEN_FILE, "w") as f:
        json.dump(cleaned, f, ensure_ascii=False)


def filter_seen(notes: list) -> list:
    """过滤掉最近几天已推送过的帖子"""
    seen = load_seen_ids()
    all_seen_ids = set()
    for ids in seen.values():
        all_seen_ids.update(ids)
    filtered = [n for n in notes if n.get("id", "") not in all_seen_ids]
    skipped = len(notes) - len(filtered)
    if skipped > 0:
        log(f"  跨天去重: 跳过 {skipped} 条已推送帖子")
    return filtered


def mark_as_seen(notes: list):
    """标记本次推送的帖子为已见"""
    seen = load_seen_ids()
    today = datetime.now().strftime("%Y-%m-%d")
    ids = seen.get(today, [])
    ids.extend(n.get("id", "") for n in notes if n.get("id"))
    seen[today] = list(set(ids))
    save_seen_ids(seen)


# ── DOM 提取 JS ──────────────────────────────────────
EXTRACT_NOTES_JS = """
JSON.stringify(
  Array.from(document.querySelectorAll("section.note-item")).map(el => {
    const a = el.querySelector("a.cover");
    const href = a ? a.getAttribute("href") : "";
    const title = (el.querySelector("[class*=title]") || {}).textContent || "";
    const authorEl = el.querySelector("[class*=author] .name, .author-wrapper .name, .nickname");
    const author = authorEl ? authorEl.textContent.trim() : "";
    const likesEl = el.querySelector("[class*=like] .count, .like-wrapper .count");
    const likes = likesEl ? likesEl.textContent.trim() : "0";
    const m = href.match(/(?:explore|search_result)\\/([a-f0-9]+)/);
    const id = m ? m[1] : "";
    return {id, title: title.trim(), author, likes};
  }).filter(n => n.id && n.title)
)
"""


# ── bb-browser 封装 ──────────────────────────────────
def bb(args: list, timeout: int = 30) -> str:
    if isinstance(args, str):
        args = args.split()
    try:
        result = subprocess.run(
            [BB_BROWSER] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log(f"  [bb-browser 超时] {' '.join(args[:3])}")
        return ""
    except Exception as e:
        log(f"  [bb-browser 异常] {e}")
        return ""


def bb_eval(js: str, timeout: int = 15) -> str:
    try:
        result = subprocess.run(
            [BB_BROWSER, "eval", js],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log("  [bb-browser eval 超时]")
        return ""
    except Exception as e:
        log(f"  [bb-browser eval 异常] {e}")
        return ""


def open_url(url: str):
    bb(["open", url], timeout=30)


def ensure_browser():
    status = bb(["status"])
    if "未运行" in status or not status:
        log("  启动浏览器...")
        bb(["open", "https://www.xiaohongshu.com/explore"], timeout=30)
        time.sleep(5)
    return True


def extract_notes_from_page() -> list:
    raw = bb_eval(EXTRACT_NOTES_JS)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


# ── 抓取逻辑 ─────────────────────────────────────────
def wait_for_notes(max_wait: int = 10) -> bool:
    for _ in range(max_wait):
        count = bb_eval('document.querySelectorAll("section.note-item").length')
        if count and count != "0":
            return True
        time.sleep(1)
    return False


def scrape_feed() -> list:
    log("  → 抓取首页推荐流...")
    open_url("https://www.xiaohongshu.com/explore")
    time.sleep(4)
    if not wait_for_notes():
        log("     首页加载超时")
        return []
    notes = extract_notes_from_page()
    log(f"     首页 {len(notes)} 条")
    return notes


def scrape_search(keyword: str) -> list:
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_search_result_notes"
    open_url(url)
    time.sleep(4)
    if not wait_for_notes(max_wait=8):
        log("     搜索页加载超时")
        return []
    notes = extract_notes_from_page()
    return notes


def scrape_all(test_mode: bool = False) -> list:
    ensure_browser()
    all_notes = []
    seen_ids = set()

    def add_notes(notes):
        added = 0
        for n in notes:
            if n["id"] not in seen_ids:
                seen_ids.add(n["id"])
                all_notes.append(n)
                added += 1
        return added

    feed_notes = scrape_feed()
    added = add_notes(feed_notes)
    log(f"     首页流共 {added} 条")

    keywords = SEARCH_KEYWORDS[:2] if test_mode else SEARCH_KEYWORDS
    for kw in keywords:
        log(f"  → 搜索「{kw}」...")
        try:
            search_notes = scrape_search(kw)
            added = add_notes(search_notes)
            log(f"     新增 {added} 条")
        except Exception as e:
            log(f"     失败: {e}")

    log(f"\n  共收集 {len(all_notes)} 条")
    return all_notes


# ── GLM API（urllib 直连，绕过 Surge 代理）────────────
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call_glm(prompt: str, max_tokens: int = 200) -> str:
    data = json.dumps({
        "model": ARK_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(
        f"{ARK_BASE_URL}/chat/completions", data=data, headers=headers
    )
    with _opener.open(request, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"].strip()


# ── 内容处理 ─────────────────────────────────────────
def pre_filter(notes: list) -> list:
    return [n for n in notes if any(kw in n.get("title", "").lower() for kw in AI_KEYWORDS)]


def parse_likes(item: dict) -> float:
    s = item.get("likes", "0").replace(",", "")
    if "w" in s or "万" in s:
        s = s.replace("w", "").replace("万", "")
        try:
            return float(s) * 10000
        except ValueError:
            return 0
    try:
        return int(s)
    except ValueError:
        return 0


def classify_one(item: dict) -> str:
    """分类单条笔记，返回 a1/a2/a3 或空"""
    likes = parse_likes(item)
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


def classify_concurrent(items: list) -> dict:
    """并发分类所有笔记，总耗时约等于单条耗时（~21s）"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not items:
        return {}
    results = {}

    def _classify(item):
        return item.get("id", ""), classify_one(item)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_classify, item): item for item in items}
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                id_, cat = future.result()
                if cat:
                    results[id_] = cat
            except Exception as e:
                log(f"  [分类异常] {e}")
            if done % 10 == 0:
                log(f"  已分类 {done}/{len(items)} 条...")
    return results


def top5(items: list) -> list:
    """去重 + 按点赞降序取前 5"""
    seen, out = set(), []
    for item in items:
        k = item.get("id", "")
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    out.sort(key=parse_likes, reverse=True)
    return out[:5]


def build_report_data(notes: list) -> dict:
    """分类 + 精选"""
    a1, a2, a3, trends = [], [], [], []
    log(f"  并发分类 {len(notes)} 条...")

    id_to_cat = classify_concurrent(notes)
    for item in notes:
        cat = id_to_cat.get(item.get("id", ""), "")
        if cat == "a1":
            a1.append(item)
        elif cat == "a2":
            a2.append(item)
        elif cat == "a3":
            a3.append(item)
        for kw in TREND_KEYWORDS:
            if kw.lower() in item["title"].lower() and kw not in trends:
                trends.append(kw)

    log(f"  分类完成: a1={len(a1)} a2={len(a2)} a3={len(a3)}")

    selected = {"a1": top5(a1), "a2": top5(a2), "a3": top5(a3)}

    # 趋势总结
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


# ── 报告格式化 ───────────────────────────────────────
def format_report(data: dict, date_str: str) -> str:
    """纯文本报告（日志 + 降级推送）"""
    lines = [f"📱 小红书 AI 日报 · {date_str}", "=" * 35, ""]
    for key, emoji, label in [("a1", "🔬", "A1｜前沿研究"), ("a2", "🛠", "A2｜产品体验"), ("a3", "💡", "A3｜实践分享")]:
        items = data.get(key, [])
        if items:
            lines.append(f"{emoji} {label}")
            for i, item in enumerate(items, 1):
                url = f"https://www.xiaohongshu.com/explore/{item.get('id', '')}"
                lines.append(f"  {i}. 【{item.get('author', '')}】{item.get('title', '')}")
                lines.append(f"     👍{item.get('likes', '0')}  🔗 {url}")
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


def build_feishu_card(data: dict, date_str: str) -> dict:
    """飞书卡片消息"""
    elements = []

    sections = [
        ("a1", "🔬", "前沿研究"),
        ("a2", "🛠", "产品体验"),
        ("a3", "💡", "实践分享"),
    ]
    for key, emoji, label in sections:
        items = data.get(key, [])
        if not items:
            continue
        elements.append({"tag": "markdown", "content": f"**{emoji} {label}**"})
        elements.append({"tag": "hr"})
        for i, item in enumerate(items, 1):
            note_id = item.get("id", "")
            url = f"https://www.xiaohongshu.com/explore/{note_id}"
            author = item.get("author", "")
            title = item.get("title", "")
            likes = item.get("likes", "0")
            md = f"**{i}. {title}**\n👤 {author}　👍 {likes}"
            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "grey",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 4,
                        "vertical_align": "top",
                        "elements": [{"tag": "markdown", "content": md}]
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "vertical_align": "center",
                        "elements": [{
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看"},
                            "type": "primary",
                            "url": url
                        }]
                    }
                ]
            })
        elements.append({"tag": "markdown", "content": ""})

    # 趋势
    a4 = data.get("a4", {})
    trends = a4.get("trends", [])
    summary = a4.get("summary", "")
    if trends or summary:
        elements.append({"tag": "markdown", "content": "**🔥 今日趋势**"})
        elements.append({"tag": "hr"})
        trend_md = ""
        if trends:
            trend_md += " · ".join(f"`{t}`" for t in trends[:8]) + "\n"
        if summary:
            trend_md += f"📈 {summary}"
        elements.append({"tag": "markdown", "content": trend_md})

    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "由 GLM-4.7 + bb-browser 自动生成"}]
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📱 小红书 AI 日报 · {date_str}"},
            "template": "purple"
        },
        "elements": elements
    }


# ── 飞书推送（绕过 Surge 代理）───────────────────────
def feishu_request(path: str, payload: dict, token: str = None) -> dict:
    url = f"https://open.feishu.cn/open-apis{path}"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with _opener.open(req, timeout=15) as resp:
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


def send_feishu_card(token: str, card: dict):
    feishu_request("/im/v1/messages?receive_id_type=open_id", {
        "receive_id": FEISHU_USER_ID,
        "msg_type": "interactive",
        "content": json.dumps(card)
    }, token)


# ── 主流程 ────────────────────────────────────────────
def main():
    load_secrets()

    args = sys.argv[1:]
    scrape_only = "--scrape" in args
    test_mode = "--test" in args
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    log(f"[{date_str}] 小红书 AI 日报 v2 (bb-browser)")

    if not scrape_only and not check_secrets():
        sys.exit(1)

    # 抓取
    all_notes = scrape_all(test_mode=test_mode)
    if not all_notes:
        log("⚠️  未抓到任何数据，浏览器可能未登录")
        if check_secrets():
            try:
                token = get_feishu_token()
                send_feishu_message(token, "⚠️ 小红书日报抓取失败：未获取到数据，请检查浏览器登录状态。")
            except Exception:
                pass
        sys.exit(1)

    if scrape_only:
        print(json.dumps({"date": date_str, "total": len(all_notes), "notes": all_notes},
                         ensure_ascii=False, indent=2))
        return

    # 过滤
    filtered = pre_filter(all_notes)
    log(f"  AI关键词过滤后 {len(filtered)} 条")

    # 跨天去重
    filtered = filter_seen(filtered)

    # 分类 + 报告
    data = build_report_data(filtered)
    report = format_report(data, date_str)
    log("\n" + report)

    # 标记已推送
    all_selected = data.get("a1", []) + data.get("a2", []) + data.get("a3", [])
    mark_as_seen(all_selected)

    # 推送卡片
    card = build_feishu_card(data, date_str)
    log("\n发送飞书卡片...")
    try:
        token = get_feishu_token()
        send_feishu_card(token, card)
        log("✅ 飞书卡片推送成功")
    except Exception as e:
        log(f"[飞书卡片推送失败] {e}")
        try:
            if not token:
                token = get_feishu_token()
            send_feishu_message(token, report)
            log("✅ 降级纯文本推送成功")
        except Exception as e2:
            log(f"[纯文本推送也失败] {e2}")


if __name__ == "__main__":
    main()
