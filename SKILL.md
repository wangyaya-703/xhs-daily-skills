---
name: xhs-daily-ai
description: >
  每日小红书 AI 内容精选推送。通过 bb-browser 抓取首页推荐流和关键词搜索结果，
  GLM-4.7 并发分类，按前沿研究/产品体验/实践分享三个维度精选 top5，
  以飞书卡片形式推送。支持跨天去重。
  触发词: "刷小红书", "xhs日报", "小红书AI日报", "今日小红书"
---

# 小红书 AI 日报

## 功能

每日自动从小红书抓取 AI 相关内容，AI 分类精选后以飞书卡片推送。

## 内容维度

- **A1 前沿研究**: 论文/评测/多模态/开源模型
- **A2 产品体验**: AI 工具推荐/新品发布/产品测评
- **A3 实践分享**: 使用心得/workflow/教程（需点赞>500）
- **A4 今日趋势**: 热词统计 + AI 风向总结

## 执行

```bash
# 正常运行
python3 run_v2.py

# 测试模式（少量数据）
python3 run_v2.py --test

# 仅抓取输出 JSON
python3 run_v2.py --scrape
```

## 配置

复制 `secrets.env.example` 为 `secrets.env` 并填入密钥。

## 依赖

- Python 3.9+（使用 /usr/bin/python3，不依赖 pip 包）
- bb-browser（通过 CDP 控制 Chrome）
- 小红书需已在 Chrome 中登录
