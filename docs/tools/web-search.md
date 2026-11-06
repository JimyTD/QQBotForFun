# 🤖 AI 问答（tools/ask_ai）

- **Status**: v2
- **Last Updated**: 2026-11-06
- **Type**: 小工具（tool），**非游戏**

---

## 1. 定位

`AI问答` 是群聊助手，不只是搜索摘要器。它按任务选择：

- 普通问题和写作、代码、推理：直接回答；
- 新闻、价格、版本、活动等时效问题：调用中国大陆 AI 搜索 API；
- “找一张图 / 壁纸 / 表情包”：搜索并发送真实图片；
- 用户发图提问：调用视觉模型理解图片；
- 同一用户 15 分钟内的追问：带少量上下文。

## 2. 触发

主入口：

```text
@我 AI问答 你的问题
@我 AI问答 找一张猫的图片
@我 AI问答 这是什么          （同时附图）
@我 AI问答 清空
```

旧入口继续兼容：`ai`、`问AI`、`查资料`、`搜索`、`搜一下`、`search`。

不用单独的 `问答` 作别名，避免与“趣味问答”游戏冲突。

## 3. 搜索源与中国大陆兼容性

**网页搜索和图片搜索统一使用博查 AI 搜索 API**：

- 端点：`POST https://api.bochaai.com/v1/web-search`
- 配置：服务器 `.env` 中的 `BOCHA_API_KEY`
- 同一响应包含 `webPages` 和 `images`
- 中国大陆服务器可直接访问，不依赖 Google、Bing 或搜狗网页抓取
- 不抓取搜索结果 HTML，不维护反爬解析器

明确移除：

- 搜狗网页搜索
- Bing 图片 HTML 解析
- 百度百科 HTML 抓取
- 无 API 的搜索引擎抓取链

未配置 `BOCHA_API_KEY` 时，联网问题会明确提示“搜索服务未配置”，不会静默退回旧源。

## 4. 视觉模型

场景 `vision` 配置在 [`config/llm.yaml`](../../config/llm.yaml)，链上均为服务器实测可识图的模型：

1. `tokenhub:hy-vision-2.0-instruct`
2. `tokenhub:hunyuan-t1-vision-20250916`
3. `tokenhub:deepseek/deepseek-v4-flash-vision-exp`

2026-11-06 在生产服务器的实测结果：三者均能通过 OpenAI `image_url` 内容块识别测试图片。

入站图片限制：

- 最多 2 张；
- 单张不超过 8 MB；
- 支持 JPEG / PNG / WebP / GIF；
- 长边超过 2048 时压缩；
- 发送给模型前校验真实图片格式。

## 5. 文件结构

```text
src/plugins/tools/ask_ai/
├── commands.py       # QQ 入口、消息组装、图片发送
├── orchestrator.py   # 意图 → 工具 → 交付
├── intent.py         # 确定性任务分类
├── media.py          # 入站图片下载、校验和压缩
├── image_search.py   # 图片候选校验与发送
├── context.py        # 短会话上下文
├── models.py         # AssistantInput / AskResult
├── prompts.py        # 聊天、检索、视觉提示词
└── service.py        # 兼容入口

src/plugins/tools/web_search/
├── provider.py       # SearchProvider 协议
├── bocha.py          # 博查 API 实现
├── models.py         # 搜索结果契约
└── service.py        # 默认 Provider 选择
```

## 6. 交付状态

| 状态 | 展示 |
|---|---|
| 直接回答 | 不显示联网说明 |
| 检索成功 | 显示最多 3 条来源 |
| 检索失败 | 明确提示“本次未取得可用的联网结果” |
| 图片成功 | 发送真实图片 + 简短说明 + 来源页 |
| 图片失败 | 明确说没找到可直接发送的合适图片 |
| 视觉失败 | 明确说这张图暂时无法识别，不让文本模型硬猜 |

## 7. 测试

```powershell
uv run pytest tests/tools/ask_ai -q
```

覆盖意图分类、博查响应解析、按需联网、搜索失败降级、图片输入校验、视觉调用、图片交付和上下文隔离。
