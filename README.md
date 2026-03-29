# xhs-daily-skills

每日小红书 AI 内容精选日报，自动抓取、AI 分类、飞书卡片推送。

**[English](#english)** | **[中文](#中文)**

---

## 中文

### 这是什么

一个面向 Code Agent（如 Claude Code、OpenClaw）的自动化 Skill：每天从小红书抓取 AI 相关帖子，用大模型分类精选后，以飞书互动卡片推送给你。

**核心流程：**

```
小红书首页推荐流 + 关键词搜索
        ↓
  AI 关键词预过滤（本地正则）
        ↓
    跨天去重（seen_ids.json）
        ↓
  GLM-4.7 并发分类（10 并发）
        ↓
  每类 Top 5（按点赞数排序）
        ↓
   飞书互动卡片推送
```

### 内容维度

| 维度 | 说明 | 选取规则 |
|------|------|---------|
| A1 前沿研究 | 论文/评测/多模态/开源模型 | Top 5 by 点赞 |
| A2 产品体验 | AI 工具推荐/新品发布/产品测评 | Top 5 by 点赞 |
| A3 实践分享 | 使用心得/workflow/教程 | Top 5 by 点赞 |
| A4 今日趋势 | 热词统计 + AI 风向总结 | 自动聚合 |

### 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.9+ | 使用系统自带 `/usr/bin/python3`，**零 pip 依赖** |
| bb-browser | 最新 | 通过 CDP 协议控制 Chrome，`npm i -g @anthropic/bb-browser` |
| Chrome | 任意 | 需已在 Chrome 中登录小红书账号 |
| 飞书应用 | — | 需创建自建应用（Luna），获取 App ID / Secret |
| 火山引擎方舟 | — | 需开通 GLM-4.7 模型访问，获取 API Key |

> **关键：脚本无任何 pip 依赖，全部使用 Python 标准库（urllib、json、subprocess 等）。**

### 安装配置

#### Step 1 — 克隆仓库

```bash
# 作为 Claude Code Skill 安装
git clone https://github.com/wangyaya-703/xhs-daily-skills.git \
  ~/.claude/skills/xhs-daily-ai

# 或安装到任意目录
git clone https://github.com/wangyaya-703/xhs-daily-skills.git
cd xhs-daily-skills
```

#### Step 2 — 配置密钥

```bash
cp secrets.env.example secrets.env
```

编辑 `secrets.env`，填入真实值：

```env
# 飞书自建应用
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here
FEISHU_USER_ID=ou_xxxxxxxxxxxxxxxx     # 接收消息的用户 open_id

# 火山引擎方舟 GLM-4.7
ARK_API_KEY=your_ark_api_key_here

# 可选：自定义模型端点
# ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
# ARK_MODEL=glm-4.7
```

**如何获取这些值：**

| 配置项 | 获取方式 |
|--------|---------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | [飞书开放平台](https://open.feishu.cn/) → 创建自建应用 → 凭证与基本信息 |
| `FEISHU_USER_ID` | 飞书管理后台 → 通讯录 → 找到目标用户 → `open_id`（以 `ou_` 开头） |
| `ARK_API_KEY` | [火山引擎方舟](https://console.volcengine.com/ark/) → 模型推理 → API Key 管理 |

**飞书应用权限要求：**
- `im:message:send_as_bot`（以机器人身份发送消息）

#### Step 3 — 自定义搜索关键词（可选）

```bash
cp config.json.example config.json
```

编辑 `config.json`：

```json
{
  "search_keywords": ["AI工具", "Claude", "Vibe Coding", "Agent", "你的关键词"]
}
```

不创建此文件则使用默认关键词：`AI工具`、`Claude`、`Vibe Coding`、`Agent`。

#### Step 4 — 确保 bb-browser 可用

```bash
# 安装 bb-browser
npm i -g @anthropic/bb-browser

# 验证
bb-browser status

# 确保 Chrome 已登录小红书
bb-browser goto https://www.xiaohongshu.com
```

#### Step 5 — 验证安装

```bash
# 测试模式：少量数据 + 实际推送
python3 run_v2.py --test

# 仅抓取：验证浏览器连通，不推送
python3 run_v2.py --scrape
```

### 使用方式

#### 手动运行

```bash
# 正常运行（每天仅推送一次）
python3 run_v2.py

# 测试模式（少量数据，不受推送锁限制）
python3 run_v2.py --test

# 强制重跑（忽略今日已推送锁）
python3 run_v2.py --force

# 仅抓取，输出 JSON 到 stdout（不分类、不推送）
python3 run_v2.py --scrape
```

#### 作为 Claude Code Skill

将仓库克隆到 `~/.claude/skills/xhs-daily-ai/` 后，在 Claude Code 中使用触发词即可：

```
> 刷小红书
> xhs日报
> 小红书AI日报
```

Agent 会自动执行 `python3 run_v2.py` 并推送结果。

#### 定时执行（crontab / HEARTBEAT）

**crontab 方式：**

```bash
# 每天 09:00 执行
0 9 * * * export PATH=/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH && cd ~/.claude/skills/xhs-daily-ai && /usr/bin/python3 run_v2.py >> run.log 2>&1
```

**OpenClaw HEARTBEAT 方式：**

在 `HEARTBEAT.md` 中添加：

~~~markdown
## 小红书 AI 日报
**触发时间**：每天 09:00（Asia/Shanghai）
### 执行步骤
**Step 1 — 运行抓取 + 分类 + 飞书推送**
```bash
export PATH=/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH
cd ~/.claude/skills/xhs-daily-ai && /usr/bin/python3 run_v2.py
```
~~~

### 防重复推送

脚本内置每日推送锁（`.push_lock`）：
- 同一天成功推送后，再次运行会自动跳过并 `exit 0`
- `--test` 模式不受锁限制
- `--force` 可强制重跑
- `--scrape` 不检查锁

### 文件说明

```
xhs-daily-skills/
├── run_v2.py              # 主脚本（抓取 + 分类 + 推送）
├── SKILL.md               # Claude Code Skill 描述文件
├── secrets.env.example    # 密钥模板
├── config.json.example    # 搜索关键词配置模板
├── .gitignore             # 排除密钥和运行时文件
├── README.md              # 本文件
│
│  # 运行时生成（已 gitignore）
├── secrets.env            # 实际密钥
├── config.json            # 实际配置
├── seen_ids.json          # 跨天去重记录（自动清理 3 天前）
├── .push_lock             # 今日推送锁
└── run.log                # 运行日志
```

### 适配其他推送渠道

脚本的推送逻辑集中在两个函数：

- `send_feishu_card(token, card)` — 发送飞书互动卡片
- `send_feishu_message(token, text)` — 发送纯文本（降级备用）

如需适配 Slack / 钉钉 / 企业微信等，替换这两个函数即可。`build_feishu_card()` 生成的数据结构可作为参考模板。

### 适配其他分类模型

分类逻辑在 `classify_one(item)` 函数中。当前使用火山引擎方舟的 GLM-4.7，修改 `ARK_BASE_URL` 和 `ARK_MODEL` 环境变量即可切换到同平台其他模型。

如需接入 OpenAI / Claude 等，替换 `classify_one()` 中的 HTTP 请求部分（标准 OpenAI-compatible API 格式）。

### 常见问题

| 问题 | 解决方案 |
|------|---------|
| `bb-browser: command not found` | 确保 PATH 包含 npm 全局 bin 目录 |
| 抓取 0 条数据 | Chrome 未登录小红书，或 bb-browser 未启动 |
| GLM 分类超时 | 检查网络代理设置，脚本已内置 `ProxyHandler({})` 绕过系统代理 |
| 飞书推送 403 | 检查应用权限 `im:message:send_as_bot` 是否开启 |
| 重复推送 | 检查 `.push_lock` 文件是否存在且日期正确 |

---

## English

### What is this

An automated Skill for Code Agents (Claude Code, OpenClaw, etc.) that scrapes AI-related posts from Xiaohongshu (Little Red Book) daily, classifies them with an LLM, and pushes a curated digest as a Feishu (Lark) interactive card.

**Core Pipeline:**

```
Xiaohongshu feed + keyword search
        ↓
  AI keyword pre-filter (local regex)
        ↓
  Cross-day dedup (seen_ids.json)
        ↓
  GLM-4.7 concurrent classification (10 workers)
        ↓
  Top 5 per category (sorted by likes)
        ↓
  Feishu interactive card push
```

### Content Categories

| Category | Description | Selection |
|----------|-------------|-----------|
| A1 Research | Papers / benchmarks / multimodal / open-source models | Top 5 by likes |
| A2 Products | AI tool reviews / new releases / product comparisons | Top 5 by likes |
| A3 Practice | Tutorials / workflows / hands-on experience | Top 5 by likes |
| A4 Trends | Hot keyword stats + AI trend summary | Auto-aggregated |

### Requirements

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.9+ | Uses system `/usr/bin/python3`, **zero pip dependencies** |
| bb-browser | latest | Controls Chrome via CDP, `npm i -g @anthropic/bb-browser` |
| Chrome | any | Must be logged into Xiaohongshu |
| Feishu App | — | Self-built app (Luna) with App ID / Secret |
| Volcengine Ark | — | GLM-4.7 model access with API Key |

> **Key: The script has zero pip dependencies — it uses only Python standard library (urllib, json, subprocess, etc.).**

### Setup

#### Step 1 — Clone

```bash
# Install as a Claude Code Skill
git clone https://github.com/wangyaya-703/xhs-daily-skills.git \
  ~/.claude/skills/xhs-daily-ai

# Or clone to any directory
git clone https://github.com/wangyaya-703/xhs-daily-skills.git
cd xhs-daily-skills
```

#### Step 2 — Configure Secrets

```bash
cp secrets.env.example secrets.env
```

Edit `secrets.env` with your actual values:

```env
# Feishu (Lark) self-built application
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here
FEISHU_USER_ID=ou_xxxxxxxxxxxxxxxx     # Target user's open_id

# Volcengine Ark GLM-4.7
ARK_API_KEY=your_ark_api_key_here

# Optional: custom model endpoint
# ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
# ARK_MODEL=glm-4.7
```

**How to obtain these values:**

| Config | Source |
|--------|--------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | [Feishu Open Platform](https://open.feishu.cn/) → Create App → Credentials |
| `FEISHU_USER_ID` | Feishu Admin → Contacts → Find user → `open_id` (starts with `ou_`) |
| `ARK_API_KEY` | [Volcengine Ark](https://console.volcengine.com/ark/) → Model Inference → API Key |

**Required Feishu app permissions:**
- `im:message:send_as_bot` (send messages as bot)

#### Step 3 — Custom Search Keywords (Optional)

```bash
cp config.json.example config.json
```

Edit `config.json`:

```json
{
  "search_keywords": ["AI工具", "Claude", "Vibe Coding", "Agent", "your-keyword"]
}
```

Without this file, defaults are used: `AI工具`, `Claude`, `Vibe Coding`, `Agent`.

#### Step 4 — Ensure bb-browser Works

```bash
# Install bb-browser
npm i -g @anthropic/bb-browser

# Verify
bb-browser status

# Ensure Chrome is logged into Xiaohongshu
bb-browser goto https://www.xiaohongshu.com
```

#### Step 5 — Verify Installation

```bash
# Test mode: small dataset + actual push
python3 run_v2.py --test

# Scrape only: verify browser connectivity, no push
python3 run_v2.py --scrape
```

### Usage

#### Manual Execution

```bash
# Normal run (pushes once per day)
python3 run_v2.py

# Test mode (small dataset, bypasses push lock)
python3 run_v2.py --test

# Force re-run (ignores daily push lock)
python3 run_v2.py --force

# Scrape only, output JSON to stdout (no classification, no push)
python3 run_v2.py --scrape
```

#### As a Claude Code Skill

Clone to `~/.claude/skills/xhs-daily-ai/`, then use trigger phrases in Claude Code:

```
> 刷小红书
> xhs日报
> 小红书AI日报
```

The agent will automatically execute `python3 run_v2.py` and push results.

#### Scheduled Execution (crontab / HEARTBEAT)

**crontab:**

```bash
# Run daily at 09:00
0 9 * * * export PATH=/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH && cd ~/.claude/skills/xhs-daily-ai && /usr/bin/python3 run_v2.py >> run.log 2>&1
```

**OpenClaw HEARTBEAT:**

Add to `HEARTBEAT.md`:

~~~markdown
## Xiaohongshu AI Daily
**Trigger**: Daily 09:00 (Asia/Shanghai)
### Steps
```bash
export PATH=/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH
cd ~/.claude/skills/xhs-daily-ai && /usr/bin/python3 run_v2.py
```
~~~

### Duplicate Prevention

Built-in daily push lock (`.push_lock`):
- After a successful push, subsequent runs on the same day auto-skip with `exit 0`
- `--test` mode is not affected by the lock
- `--force` overrides the lock
- `--scrape` does not check the lock

### File Structure

```
xhs-daily-skills/
├── run_v2.py              # Main script (scrape + classify + push)
├── SKILL.md               # Claude Code Skill descriptor
├── secrets.env.example    # Secrets template
├── config.json.example    # Search keywords config template
├── .gitignore             # Excludes secrets and runtime files
├── README.md              # This file
│
│  # Generated at runtime (gitignored)
├── secrets.env            # Actual secrets
├── config.json            # Actual config
├── seen_ids.json          # Cross-day dedup records (auto-cleans after 3 days)
├── .push_lock             # Daily push lock
└── run.log                # Execution log
```

### Adapting to Other Push Channels

Push logic is concentrated in two functions:

- `send_feishu_card(token, card)` — sends Feishu interactive card
- `send_feishu_message(token, text)` — sends plain text (fallback)

To adapt for Slack / DingTalk / WeCom, replace these two functions. The data structure from `build_feishu_card()` can serve as a reference template.

### Adapting to Other Classification Models

Classification logic is in `classify_one(item)`. Currently uses GLM-4.7 on Volcengine Ark. Change `ARK_BASE_URL` and `ARK_MODEL` environment variables to switch models on the same platform.

For OpenAI / Claude integration, replace the HTTP request in `classify_one()` — it uses standard OpenAI-compatible API format.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| `bb-browser: command not found` | Ensure PATH includes npm global bin directory |
| 0 notes scraped | Chrome not logged into Xiaohongshu, or bb-browser not running |
| GLM classification timeout | Check network proxy settings; script has built-in `ProxyHandler({})` to bypass system proxy |
| Feishu push 403 | Verify app permission `im:message:send_as_bot` is enabled |
| Duplicate pushes | Check if `.push_lock` file exists with correct date |

### Secret Leak Guard

Install local pre-commit scan:

```bash
./scripts/security/install_precommit_hook.sh
```

Run manual scans:

```bash
python3 scripts/security/scan_secrets.py --mode repo
python3 scripts/security/scan_secrets.py --mode history
```

CI scan workflow:

- `.github/workflows/secret-leak-scan.yml`
- Runs on push / pull request / daily schedule
- Scans both current files and full git history

### License

MIT
