# 🍱 今天吃什么（tools/food）

- **Status**: Draft v0.1
- **Last Updated**: 2026-04-30
- **Type**: 小工具（tool），**非游戏**（无对局、无输赢、无经济）

---

## 1. 定位与边界

### 1.1 这是什么

为群聊"吃什么"选择困难症提供一键甩锅方案：机器人从一个预设菜单库里随机抽一道菜，返回"菜名 + 2-3 句说明 + 图片"。交互到此结束。

### 1.2 这不是游戏

**显式不走 `GameBase` 框架**，理由：
- 没有对局概念（一条命令一个结果，不存状态）
- 没有输赢（吃啥没对错）
- 没有经济（吃个饭加分怪怪的）
- 没有多玩家交互（发命令者即结果接收者）

硬要套 GameBase 会引入不必要的 session / 状态机 / on_end 等概念，反而不优雅。作为**拔插式小工具**独立实现。

### 1.3 代码框架角色

食物功能是 `src/plugins/tools/` 目录下**第一个"工具型功能"**，为将来同类功能（如"掷骰子"、"黄历"、"算命"等）树立**目录规范**。

```
src/plugins/
  games/              # 有对局概念：海龟汤、趣味问答
    turtle_soup/
    trivia/
  tools/              # ⬅️ 无对局一次性功能
    food/             # 吃什么（本文档对象）
      __init__.py
      commands.py     # 命令注册
      service.py      # 业务逻辑
      storage.py      # DB 交互（CRUD food_items）
    # <future>/       # 未来新工具
```

每个 `tools/<xxx>/` 自包含：
- 自己注册自己的命令（在 `commands.py` 里 `on_command` + aliases）
- 自己管自己的 DB 表（在 `storage.py` 里用 core.storage 的 session）
- 不依赖其他 tool、不被其他 tool 依赖
- 主应用 `src/bot.py` 里一行 import 即可装载；移除也只需删目录 + 删那行 import

---

## 2. 命令

| 命令 | 别名 | 效果 |
|---|---|---|
| `/吃什么` | `今天吃什么`, `eat`, `food` | 从库里随机抽 1 道菜，返回 文字卡片 + 图片 |

**不**支持：
- 参数筛选（`/吃什么 辣` 之类）——v0.1 简单直给，未来再说
- 重抽（"再来一个"）——直接再发一次命令即可
- 记录/统计——v0.1 不存历史

---

## 3. 数据模型

### 3.1 DB 表

```sql
CREATE TABLE food_items (
    id           TEXT PRIMARY KEY,         -- 英文 snake_case，如 "malatang"
    name         TEXT NOT NULL,            -- 展示名，如 "麻辣烫"
    description  TEXT NOT NULL,            -- 2-3 句说明文案
    image_path   TEXT,                     -- 相对项目根的路径，如 "resources/foods/malatang.jpg"；可空
    tags         TEXT,                     -- 逗号分隔的标签（辣/汤/快餐/早餐/...），未来筛选用
    created_at   INTEGER NOT NULL          -- Unix epoch 秒
);
```

### 3.2 种子数据

- `seeds/foods.json` ——50 道菜的 JSON 列表
- 字段：`id`、`name`、`description`、`image_path`、`tags`
- 通过 `scripts/seed_foods.py` 批量导入到 DB
- **种子由 AI 根据"2026 年网络流行餐饮"搜索后自行整理**（覆盖中餐 ~30 / 外卖快餐 ~10 / 西餐 ~5 / 早餐 ~5）

### 3.3 图片

- 位置：`resources/foods/<id>.jpg`
- 生成方式：`image_gen` 工具批量生成（每道菜一张）
- 风格：**自由发挥**，只要图片内容和菜名相关即可（不强制统一风格）
- 大小预估：50 张 × ~80KB ≈ 4 MB，可入 git
- 缺图容错：`image_path` 允许为空；`storage.pick_random()` 返回的 `image_path` 若对应文件不存在，命令处理器仅发送文字卡片，不报错

---

## 4. 工作流

### 4.1 Bot 端流程

```
用户发 /吃什么
  ↓
commands._handle_food()
  ↓
service.pick_random() → FoodItem
  ↓
组装 MessageSegment:
  - render.text_card(name, description)
  - MessageSegment.image(file://<absolute_path>) （若图存在）
  ↓
bot.send() 一次性发出
```

### 4.2 CLI 端流程

由于 CLI 是纯文本终端（`cmd.exe` / `PowerShell`）**不支持图片显示**，CLI 的行为是：

```
用户输入 /吃什么
  ↓
cli_adapter.handle_food()
  ↓
pick_random() → FoodItem
  ↓
打印：
  🍱 今天吃 ——  <name>
  
  <description>
  
  📷 图片: resources/foods/<id>.jpg
```

末行**显示图片路径而非实际图片**，让 CLI 用户知道图存在，想看可以自己打开。

---

## 5. 与 CLI-Bot 对齐铁律的关系

`docs/13-cli-bot-parity.md` 的铁律要求 CLI 和 Bot 的**玩家可见行为 1:1 对齐**（决策点、指令、选项、状态机、判定逻辑）。

吃什么功能遵守：
- ✅ 命令集一致：两端都支持 `/吃什么` 及其别名
- ✅ 数据一致：两端从同一张 `food_items` 表读取
- ✅ 文案一致：name 和 description 完全相同

**豁免**：
- ⚠️ 图片展示：CLI 只显示路径、Bot 发真图——这是**终端能力限制**，不是"行为不一致"。铁律允许这类"不可抗力"差异（类比：CLI 有 debug 输出、Bot 没有）。

---

## 6. 开发与运维

### 6.1 本地新增一道菜

手动编辑 `seeds/foods.json` 加一条，然后：
```powershell
uv run python scripts/seed_foods.py    # upsert 模式，不覆盖已有
```

图片有则放 `resources/foods/<id>.jpg`，没有则 `image_path` 字段留空。

### 6.2 本地重新生成某张图

直接用 `image_gen` 工具或外部绘图软件生成一张 jpg，放到对应路径即可。下次命令触发读到新图。

### 6.3 测试

- 单元测试：`tests/tools/food/test_pick_random.py`
  - 空库返回 None + 友好错误信息
  - 随机分布（粗校验）
  - 图片文件缺失不阻塞
- 手动验证：群里 `/吃什么` 或 CLI 里选小工具菜单

---

## 7. 未来扩展点（**不在 v0.1 做**）

记录在此防止以后"突然想到"时重复设计：

- **按标签筛选**：`/吃什么 辣` / `/吃什么 清淡`（已预留 `tags` 字段）
- **群内投票选菜**：升级为游戏，走 GameBase
- **基于时间/天气/地理位置推荐**：需要外部 API（高德/天气）
- **记录每次抽到的菜 + 群/个人统计**：加 `food_history` 表
- **用户自定义加菜单**：`/吃什么 加 <菜名> <说明>` + 审核机制
- **图片懒加载 / CDN**：当菜单 > 500 道时考虑

---

## 8. 版本

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-04-30 | 初版：命令注册、50 道种子、DB 表、图片、CLI 支持 |
