# 🔍 联网搜索（tools/web_search → 合并到 ask_ai）

- **Status**: v1.0
- **Last Updated**: 2026-05-08
- **Type**: 小工具（tool），**非游戏**（无对局、无输赢、无经济）

---

## 1. 定位与边界

### 1.1 这是什么

为群聊提供联网搜索能力。统一入口（查资料/搜索/问AI/ai），**搜索优先**：默认先联网搜索获取实时信息，由 LLM 总结后回复；仅当问题明显无需搜索时 fallback 到纯 LLM。

### 1.2 技术架构

```
用户: @机器人 查资料/搜索 xxx
  ↓
ask_ai 插件（判断是否需要搜索）
  ↓ 默认走搜索
httpx GET 搜狗网页搜索
  ↓ 解析 HTML 提取 top 5 结果（标题 + 摘要）
拼入 LLM prompt
  ↓
LLM（glm-4-flashx, temperature=0.3）总结输出 ≤300 字
  ↓
回复用户（含来源列表）
```

### 1.3 为什么用搜狗

国内服务器（腾讯云广州）网络限制测试结果：
- Google：超时
- DuckDuckGo（API/库）：超时
- Wikipedia：超时
- Bing：被强制重定向到 cn.bing.com，搜索质量极差
- 百度：反爬严格，无 cookie 返回空页面
- **搜狗：✅ 直接 GET 即可，结果精准，无需 API Key**

---

## 2. 交互设计

### 2.1 触发方式（统一入口）

- `@机器人 查资料 <问题>`
- `@机器人 搜索 <问题>`
- `@机器人 搜一下 <问题>`
- `@机器人 问AI <问题>`
- `@机器人 ai <问题>`
- `@机器人 search <问题>`

### 2.2 跳过搜索的情况

仅以下极少情况直接走纯 LLM（搜索倾向大）：
- 纯数学表达式（如 `1+1`）
- 简单打招呼（`你好`、`hi`）
- 问机器人自身（`你是谁`）

### 2.3 回复格式

```
🔍 查资料
━━━━━━━━━━━━━━━━
<LLM 基于搜索结果的总结，≤300 字>

📎 来源：
1. <标题>
2. <标题>
3. <标题>
────────────────
Q: <用户原始问题>
```

---

## 3. 文件清单

```
src/plugins/tools/ask_ai/
├── __init__.py       # PluginMetadata（搜索优先版）
└── commands.py       # 统一命令处理器（搜索优先 + fallback）

src/plugins/tools/web_search/
└── searxng.py        # 搜狗搜索客户端（文件名保留历史，实际用搜狗）

scripts/cli_adapters/
└── web_search.py     # CLI adapter（统一入口）
```

---

## 4. 注意事项

- 不依赖任何额外容器/服务，bot 容器直接 HTTP 请求搜狗
- 搜狗可能偶尔反爬限流，此时自动 fallback 到纯 LLM
- LLM 总结时 system prompt 强调"基于搜索结果回答，不编造信息"
- 搜索失败不影响 bot 其他功能（graceful degradation）
