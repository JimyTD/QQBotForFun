# Work Reminder · 工作定时提醒

**Status**: Design v3 (implementation-ready)  
**Date**: 2026-05-07

---

## 0. 概述

轻量级定时提醒工具，**不是闹钟，是有"人味"的随机提醒**。

机器人在工作日将一天划分为多个"主题窗口"，每个窗口内**随机选一个时间点**发送提醒消息（文字或梗图），提醒站立活动、放松休息、下班等。

**核心特性：**
- 工作日触发（周一到周五），周末静默
- 每个窗口每天最多触发 1 次，触发时间每天不同（随机）
- 概率发送（每个窗口独立 roll，不一定每天都触发）
- 内容随机（文字 + 梗图混合，所有启用群收到同一条消息）
- 全群开关（任何群友可控制本群是否启用）

**设计哲学：**
- ✅ 随机、不可预测、有惊喜感
- ✅ 内容与时段匹配（早上说站立，傍晚说下班）
- ❌ 不是固定时间精确触发
- ❌ 不会每天同一时间响

---

## 1. 用户体验

### 1.1 开启/关闭

```
任何群友:
@机器人 提醒 开

Bot:
✅ 已为本群开启工作提醒
工作日会在各时段随机发送提醒（吃饭/活动/下班等）

任何群友:
@机器人 提醒 关

Bot:
✅ 已为本群关闭工作提醒
```

**说明：**
- 无权限要求，任何群友都可以开/关
- 存储 `group_id`，作用于整个群
- 默认**关闭**（新群需要手动开启）

---

### 1.2 提醒效果示例

**某工作日（随机触发结果）：**

10:47 —— 🦴 脖子还好吗？转转头看看窗外

（下午茶窗口今天没命中，静默）

20:13 —— ⏰ 都 8 点了还不走？准时下班是对公司最起码的尊重

---

## 2. 技术设计

### 2.1 时段窗口

| 窗口 | 时间范围 | 概率 | 主题 | 设计理由 |
|------|---------|------|------|---------|
| 上午活动 | 10:00 ~ 11:30 | 60% | 站立/喝水/活动 | 坐了 1~2.5h 该动动 |
| 下午茶 | 14:30 ~ 16:30 | 50% | 喝咖啡/休息/看远处 | 午后犯困期 |
| 下班 | 19:00 ~ 21:00 | 70% | 下班/别卷/收工 | 适配加班人群 |

**统计期望：** 平均每天触发 1.8 条，最多 3 条，最少 0 条（概率 ~5.4%）。

---

### 2.2 调度机制

**核心思路：** 每天凌晨（或 bot 启动时）对每个窗口：
1. Roll 一次概率，决定今天该窗口**发不发**
2. 如果发 → 在窗口时间范围内随机选一个时间点，注册一次性定时任务
3. 到点发送，内容从该窗口主题池里随机选一条

**实现方式：**

```python
import random
from datetime import date, time, datetime, timedelta
from core.scheduler import schedule_cron, schedule_once

WINDOWS = {
    "morning": {
        "start": time(10, 0),
        "end": time(11, 30),
        "probability": 0.6,
    },
    "afternoon": {
        "start": time(14, 30),
        "end": time(16, 30),
        "probability": 0.5,
    },
    "offwork": {
        "start": time(19, 0),
        "end": time(21, 0),
        "probability": 0.7,
    },
}


async def _plan_today() -> None:
    """每天 00:05 触发，为当天所有窗口规划发送时间。仅工作日执行。"""
    today = date.today()
    if today.weekday() >= 5:  # 周末不发
        return

    for slot_name, config in WINDOWS.items():
        # 概率判定
        if random.random() > config["probability"]:
            continue

        # 在窗口内随机选一个分钟
        start_min = config["start"].hour * 60 + config["start"].minute
        end_min = config["end"].hour * 60 + config["end"].minute
        chosen_min = random.randint(start_min, end_min - 1)
        trigger_time = datetime.combine(today, time(chosen_min // 60, chosen_min % 60))

        # 注册一次性定时任务
        await schedule_once(trigger_time, _send_reminder, slot_name)
```

**每日规划触发：** 用 cron `5 0 * * 1-5`（工作日 00:05）调用 `_plan_today()`。

**Bot 启动补偿：** 如果 bot 在当天启动时（非 00:05），检查是否已规划过今天——若没有则立即执行 `_plan_today()`（仅保留当前时刻之后的窗口）。

---

### 2.3 内容池配置

```python
CONTENT_POOL: dict[str, list[ContentItem]] = {
    "morning": [
        {"type": "text", "msg": "🧘 已经坐了快 2 小时了，站起来活动活动吧~"},
        {"type": "text", "msg": "💪 久坐伤身，起来扭扭脖子！"},
        {"type": "text", "msg": "☕ 去接杯水顺便走走？"},
        {"type": "text", "msg": "🦴 脖子还好吗？转转头看看窗外"},
        {"type": "text", "msg": "🚶 起来走两步，坐太久血液不循环"},
        {"type": "image", "category": "stand"},
    ],
    "afternoon": [
        {"type": "text", "msg": "☕ 下午茶时间！喝点东西提提神"},
        {"type": "text", "msg": "🧘 坐了一下午了，起来动一动"},
        {"type": "text", "msg": "👀 看看远处让眼睛休息一下"},
        {"type": "text", "msg": "🍵 喝口水，下午继续冲"},
        {"type": "image", "category": "afternoon"},
    ],
    "offwork": [
        {"type": "text", "msg": "🏃 下班啦！准时下班快乐每一天~"},
        {"type": "text", "msg": "🌆 该走了该走了，明天再卷也不迟"},
        {"type": "text", "msg": "💼 记得关电脑，别等保安赶人"},
        {"type": "text", "msg": "🎉 恭喜你又摸了一天鱼！"},
        {"type": "text", "msg": "⏰ 准时下班是对公司最起码的尊重"},
        {"type": "text", "msg": "🚪 都这个点了还不走？"},
        {"type": "image", "category": "offwork"},
    ],
}
```

---

### 2.4 数据存储

**表名：`tool_reminder_groups`**（遵循 `tool_` 前缀约定）

| 字段 | 类型 | 说明 |
|------|------|------|
| `group_id` | String(32), PK | QQ 群号 |
| `enabled` | Boolean | 是否启用（默认 False） |
| `enabled_at` | DateTime | 最近一次开启时间 |
| `enabled_by` | String(32) | 开启者 QQ 号 |

```python
# models.py
from core.storage import Base, register_model

class ReminderGroup(Base):
    __tablename__ = "tool_reminder_groups"
    ...

register_model(ReminderGroup, migration_group="tool_reminder")
```

---

### 2.5 发送逻辑

```python
import random
import base64
from pathlib import Path
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageSegment
from core.session import broadcast  # ← 走 core.session，不直接调 bot API

_ROOT = Path(__file__).resolve().parents[4]
# 图片文件列表在启动时预缓存，不在每次触发时 glob
_image_cache: dict[str, list[Path]] = {}


def _load_image_cache() -> None:
    """启动时扫描，避免定时触发时做同步 IO。"""
    categories = {
        "stand": "resources/reminders/stand_*",
        "afternoon": "resources/reminders/afternoon_*",
        "offwork": "resources/reminders/offwork_*",
    }
    for cat, pattern in categories.items():
        _image_cache[cat] = list(_ROOT.glob(pattern))


async def _send_reminder(slot: str) -> None:
    """一次性定时任务触发回调。"""
    # 1. 查询启用的群
    enabled_groups = await get_enabled_groups()
    if not enabled_groups:
        return

    # 2. 随机选内容
    pool = CONTENT_POOL[slot]
    item = random.choice(pool)

    # 3. 构造消息
    if item["type"] == "text":
        msg = item["msg"]
    elif item["type"] == "image":
        images = _image_cache.get(item["category"], [])
        if images:
            img_path = random.choice(images)
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            msg = MessageSegment.image(f"base64://{b64}")
        else:
            return  # 图片缺失时静默跳过

    # 4. 群发（静默失败）
    for group_id in enabled_groups:
        try:
            await broadcast(int(group_id), msg)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[reminder] send failed group={group_id}: {e}")
```

---

### 2.6 图片素材

**目录结构：**
```
resources/
└── reminders/          # 梗图
    ├── stand_*.jpg     # 站立/喝水/伸展（5 张）
    ├── afternoon_*.jpg # 下午茶/咖啡（7 张）
    └── offwork_*.jpg   # 下班/摸鱼（8 张）
```

**已有素材统计：**
| 分类 | 数量 | 来源 |
|------|------|------|
| stand | 5 张 | ChineseBQB |
| afternoon | 7 张 | ChineseBQB |
| offwork | 8 张 | ChineseBQB |

---

## 3. 指令清单

| 指令 | 别名 | 说明 |
|------|------|------|
| `提醒 开` | `reminder on` | 为本群开启定时提醒 |
| `提醒 关` | `reminder off` | 为本群关闭定时提醒 |

（按项目约定无斜杠前缀，群聊需 @机器人 触发。）

---

## 4. 架构对接清单

| ID | 任务 | 文件 |
|---|---|---|
| 1 | 创建 `src/plugins/tools/reminder/` 目录（`__init__.py` / `models.py` / `commands.py` / `scheduler_jobs.py`） | — |
| 2 | `models.py`：定义 `ReminderGroup` + `register_model(..., "tool_reminder")` | `src/plugins/tools/reminder/models.py` |
| 3 | `storage.py`：`_import_all_models()` 加 import reminder models | `src/core/storage.py` |
| 4 | `commands.py`：`提醒 开/关` 指令处理器 | `src/plugins/tools/reminder/commands.py` |
| 5 | `scheduler_jobs.py`：窗口配置 + 内容池 + `_plan_today` + `_send_reminder` + 图片缓存 | `src/plugins/tools/reminder/scheduler_jobs.py` |
| 6 | `__init__.py`：`on_startup` 中注册每日规划 cron + 首次启动补偿 + 调用 `_load_image_cache()` | `src/plugins/tools/reminder/__init__.py` |
| 7 | `bot.py`：`_load_plugins()` 加 `nonebot.load_plugin("src.plugins.tools.reminder")` | `src/bot.py` |
| 8 | 创建 migration（Alembic）| `migrations/versions/xxx_add_tool_reminder.py` |
| 9 | 单元测试 | `tests/test_reminder.py` |

---

## 5. 可选扩展（基础版不做）

| 功能 | 说明 |
|------|------|
| 周五彩蛋 | 周五下班窗口概率 100% + 专属文案"周末快乐！" |
| 自定义时段 | 管理员配置窗口时间范围 |
| 自定义文案 | 群友投稿提醒语 |
| 天气联动 | 下雨时提示"记得带伞" |
| `/提醒 状态` | 查看本群开关状态 + 今日规划 |

---

## 6. 约定与限制

- **轻量工具**，不接入游戏框架（`GameBase`），不入 `docs/10-roadmap.md`
- **不做 CLI 模拟**（定时任务无法在 CLI 里测试，本地测试用单元测试覆盖）
- **群消息通知**，不支持私聊
- **零经济交互**，不涉及 coin/score
- **静默失败**，发送失败只记日志，不影响其他群
- **全局 roll + 全群同内容**，不做每群独立随机
- **每窗口每天最多 1 条**，不会同一时段重复提醒

---

## 7. 测试策略

### 单元测试（`tests/test_reminder.py`）

- `_plan_today()`：mock `random`，验证工作日生成正确数量的一次性任务，周末不生成
- 概率逻辑：验证阈值判断正确
- 时间随机：验证选出的时间点在窗口范围内
- 开关逻辑：开启/关闭后查询 DB 状态正确
- 消息构造：文字消息 → str；图片消息 → `MessageSegment.image(base64://...)`
- 图片缓存：verify `_load_image_cache` 正确扫描
- 启动补偿：模拟非 00:05 启动，验证仅规划未过期窗口

### 手动测试

- 本地临时改所有概率为 1.0 + 窗口范围设为"当前时间 +1 分钟"快速验证
- 检查群里收到消息 + 图片正常显示

---

## 8. 部署注意事项

- 确保服务器时区正确（中国 UTC+8），APScheduler 按系统时区触发
- `resources/reminders/` 图片需一起打包到 Docker 镜像或挂载
- 首次上线建议先在测试群 `提醒 开`，验证通过后再通知其他群
- Bot 重启后会自动补偿当日规划（无需手动干预）

---

**END**
