# 🔍 AI / 查资料（tools/ask_ai）

- **Status**: v2
- **Last Updated**: 2026-11-06
- **Type**: 小工具（tool），**非游戏**

---

## 1. 定位

`ai` / `查资料` 起手，后面整句话按群聊助手处理。入口保持原样：
用户不需要在问题里额外指定“看图 / 搜图 / 联网”等功能参数。

## 2. 触发

```text
@我 ai 你的问题
@我 查资料 你的问题
@我 搜索 你的问题
@我 ai 这是什么              （同时附图）
@我 ai 清空
```

保留旧别名：`问AI`、`ai`、`搜索`、`搜一下`、`search`。

## 3. 能力

- 普通问题：直接回答；
- 时效问题：走原有网页搜索链路；
- 图片消息：读取 QQ 图片并交给视觉模型；
- 短追问：同一用户 15 分钟内的“继续 / 第二点展开”等；
- 上下文按群 + 用户隔离，可主动清空。

## 4. 搜索源

文字联网使用项目原有搜索链路，不需要额外搜索账号。

不使用新的外部搜索账号作为前置条件。图片搜索在旧链路上没有可靠的图片结果能力，
因此当前明确返回“图片搜索暂不可用”，不伪装成可用，也不生成假图冒充搜索结果。

## 5. 文件结构

```text
src/plugins/tools/ask_ai/
├── commands.py       # QQ 入口、消息组装、结果交付
├── orchestrator.py   # 意图 → 能力 → 结果
├── intent.py         # 内部意图判断
├── media.py          # QQ 图片读取、校验、压缩
├── context.py        # 短上下文
├── models.py         # AssistantInput / AskResult
└── prompts.py        # 聊天、检索、视觉提示词

src/plugins/tools/web_search/
├── searxng.py        # 原有文字搜索链路
├── models.py         # 结果契约
└── service.py        # 搜索入口
```

## 6. 验证

```powershell
uv run pytest tests/tools/ask_ai -q
```

原入口保留、文字搜索、图片输入读取、视觉场景和上下文隔离均为必测项。
