# ADR 0002 · 机器人框架选型：NoneBot2

- **Status**: Accepted
- **Date**: 2026-04-28
- **Decider**: @owner

## 背景

在选定 NapCat 作为协议端后，业务层需要一个框架处理事件分发、插件管理、路由等。
候选方案：

| 框架 | 语言 | 协议支持 | 特点 |
|---|---|---|---|
| **NoneBot2** | Python | 多协议（OneBot/QQ 官方/Discord/…） | 生态最大 |
| Koishi | TypeScript | 多协议 | 前端友好，插件商店丰富 |
| LangBot | Python | OneBot | 聚焦 LLM 对话 |
| Mirai Console | Java/Kotlin | Mirai only | 绑定 Mirai |
| 自研 | — | — | 成本高 |

## 决策

**采用 NoneBot2 + nonebot-adapter-onebot**。

## 理由

### 为什么 NoneBot2

1. **Python 生态**：项目大量使用 LLM、图像处理、数据分析，Python 库最全
2. **异步架构（FastAPI 底子）**：天然适合长时间等待的小游戏场景
3. **协议层可替换**：通过 adapter 机制，**同一套业务代码**可以跑在 OneBot、官方 QQ、Discord、Telegram 上
4. **插件商店 1000+**：定时任务、数据库、图片渲染等刚需都有现成插件
5. **社区活跃**：中文文档质量高，2026 年仍是中文圈最主流的 Bot 框架
6. **与 NapCat 一等公民支持**：NapCat 官方文档把 NoneBot 列为首选
7. **matcher / rule / permission** 的设计抽象合理，适合插件化开发

### 为什么不选其他

- **Koishi**：
  - 优点：前端友好，多平台适配能力更好
  - 缺点：对 Python/LLM 生态访问需要绕路（Node ↔ Python 跨语言），游戏逻辑 + LLM 混编不够流畅
  - 社区在国内偏中小规模
- **LangBot**：
  - 聚焦"LLM 套壳"，**不是**通用机器人框架
  - 没有良好的插件隔离机制，不适合多游戏平台
- **Mirai Console**：
  - Java 生态不适合 LLM / 图像处理快速迭代
  - 与 NapCat 不兼容
- **自研**：
  - 重复造轮子，回报低
  - 后续人力接手成本高

## 关键设计约束

为了保留**协议层可替换性**，项目强制约束：

- **游戏层禁止直接 import NoneBot**，一律走 `core.*`
- Core 层是**唯一**与 NoneBot 交互的地方
- 用到 NoneBot 特性时优先选 adapter 中立的 API（如 `UniversalMessage`）

这样未来切换到 `nonebot-adapter-qq`（官方 API）或者 Discord adapter 时，Core 只需针对性修改，Games 层几乎不动。

## 版本策略

- 锁定 **NoneBot2 2.4.x**（当前稳定线）
- Python **3.11**（NoneBot 官方推荐）
- 每季度评估一次升级

## 影响

- 团队成员需掌握 Python + async/await
- 使用 NoneBot 插件商店扩展能力（apscheduler、orm、htmlrender 等）
- 编码规范遵循 NoneBot 约定（插件目录、matcher 命名等）
