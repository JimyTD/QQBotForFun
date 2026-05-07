# Work Reminder · 工作定时提醒

**Status**: Design v1  
**Owner**: @owner  
**Date**: 2026-05-07

---

## 0. 概述

轻量级定时提醒工具，零交互纯氛围。机器人在固定时间点按概率向群发送提醒消息（文字或梗图），提醒站立活动、下班、摸鱼等。

**核心特性：**
- 定时触发（5 个时段：上午/午休/下午茶/下班/晚间）
- 概率发送（不是每次都发，避免刷屏）
- 内容随机（文字 + 梗图混合）
- 全群开关（任何群友可控制本群是否启用）

---

## 1. 用户体验

### 1.1 开启/关闭

```
任何群友:
@机器人 提醒 开

Bot:
✅ 已为本群开启工作提醒
每天会在固定时间随机发送提醒消息（站立/下班/摸鱼等）

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

### 1.2 定时提醒示例

**10:00 上午场（概率 30%）**

```
Bot:
🧘 已经坐了 2 小时了，站起来活动活动吧~
```

或

```
Bot:
[发送梗图: 站立活动相关]
```

**12:00 午休场（概率 50%）**

```
Bot:
🍱 今天吃什么？试试 @机器人 吃什么
```

或

```
Bot:
[发送食物图片]
```

**18:00 下班场（概率 60%）**

```
Bot:
🏃 下班啦！准时下班快乐每一天~
```

或

```
Bot:
[发送下班梗图]
```

---

## 2. 技术设计

### 2.1 定时任务

使用 `core.scheduler.schedule_cron` 注册 5 个定时任务：

| 时段 | 触发时间 | 概率 | 主题 |
|------|---------|------|------|
| 上午 | 10:00 | 30% | 站立活动、喝水 |
| 午休 | 12:00 | 50% | 吃饭、午睡、摸鱼 |
| 下午茶 | 15:00 | 40% | 喝咖啡、休息 |
| 下班 | 18:00 | 60% | 下班提醒、关电脑 |
| 晚间 | 21:00 | 20% | 早睡、别卷 |

**Cron 表达式：**
```python
"0 10 * * *"  # 每天 10:00
"0 12 * * *"  # 每天 12:00
"0 15 * * *"  # 每天 15:00
"0 18 * * *"  # 每天 18:00
"0 21 * * *"  # 每天 21:00
```

---

### 2.2 概率池配置

```python
REMINDER_SLOTS = {
    "morning": {
        "probability": 0.3,
        "content": [
            {"type": "text", "msg": "🧘 已经坐了 2 小时了，站起来活动活动吧~"},
            {"type": "text", "msg": "💪 久坐伤身，起来扭扭脖子！"},
            {"type": "text", "msg": "☕ 去接杯水顺便走走？"},
            {"type": "image", "pattern": "resources/reminders/stand_*.jpg"},
        ],
    },
    "lunch": {
        "probability": 0.5,
        "content": [
            {"type": "text", "msg": "🍱 今天吃什么？试试 @机器人 吃什么"},
            {"type": "text", "msg": "😴 午休记得眯 20 分钟，下午不犯困"},
            {"type": "text", "msg": "🏃 吃完饭走一走，活到九十九"},
            {"type": "image", "pattern": "resources/foods/*.jpg"},  # 复用食物图
        ],
    },
    "afternoon": {
        "probability": 0.4,
        "content": [
            {"type": "text", "msg": "☕ 下午茶时间！喝点咖啡提提神"},
            {"type": "text", "msg": "🧘 坐了 3 小时了，起来动一动"},
            {"type": "text", "msg": "🎯 还有 3 小时下班，冲鸭！"},
            {"type": "image", "pattern": "resources/reminders/afternoon_*.jpg"},
        ],
    },
    "offwork": {
        "probability": 0.6,
        "content": [
            {"type": "text", "msg": "🏃 下班啦！准时下班快乐每一天~"},
            {"type": "text", "msg": "🌆 六点了，该溜了吧？"},
            {"type": "text", "msg": "💼 记得关电脑哦"},
            {"type": "text", "msg": "🎉 恭喜你又摸了一天鱼！"},
            {"type": "text", "msg": "⏰ 准时下班是对公司最起码的尊重"},
            {"type": "image", "pattern": "resources/reminders/offwork_*.jpg"},
        ],
    },
    "night": {
        "probability": 0.2,
        "content": [
            {"type": "text", "msg": "🌙 还在加班？注意休息啊"},
            {"type": "text", "msg": "😴 该睡觉了，明天还要搬砖呢"},
            {"type": "text", "msg": "💻 别卷了，早点休息"},
            {"type": "image", "pattern": "resources/reminders/sleep_*.jpg"},
        ],
    },
}
```

---

### 2.3 数据存储

**表名：`reminder_enabled_groups`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `group_id` | String (PK) | QQ 群号 |
| `enabled` | Boolean | 是否启用（默认 False） |
| `enabled_at` | DateTime | 开启时间 |
| `enabled_by` | String | 开启者 QQ 号 |

**操作：**
- `/提醒 开` → `INSERT OR UPDATE enabled=True`
- `/提醒 关` → `UPDATE enabled=False`
- 定时任务触发时 → `SELECT group_id WHERE enabled=True`

---

### 2.4 发送逻辑

```python
async def _send_reminder(slot: str) -> None:
    """定时槽触发回调"""
    config = REMINDER_SLOTS[slot]
    
    # 1. 概率判定
    if random.random() > config["probability"]:
        return  # 本次不发
    
    # 2. 查询启用的群
    enabled_groups = await get_enabled_groups()
    if not enabled_groups:
        return
    
    # 3. 随机选内容
    item = random.choice(config["content"])
    
    # 4. 构造消息
    if item["type"] == "text":
        msg = item["msg"]
    elif item["type"] == "image":
        # 从 pattern 匹配的文件中随机选一张
        images = glob.glob(item["pattern"])
        if images:
            img_path = random.choice(images)
            msg = _build_image_message(img_path)  # base64 编码
        else:
            msg = "🎉 [图片加载失败]"
    
    # 5. 群发
    for group_id in enabled_groups:
        try:
            await send_group_message(group_id, msg)
        except Exception as e:
            logger.warning(f"提醒发送失败 group={group_id}: {e}")
```

---

### 2.5 图片资源

**目录结构：**

```
resources/
├── foods/                   # 已有（复用）
│   ├── baozi.jpg
│   └── ...
└── reminders/               # 新增
    ├── stand_1.jpg          # 站立活动
    ├── stand_2.gif
    ├── offwork_1.jpg        # 下班
    ├── offwork_2.jpg
    ├── afternoon_1.jpg      # 下午茶
    ├── sleep_1.jpg          # 早睡
    └── ...
```

**素材来源：**
- 从 ChineseBQB / EmojiPackage / 网络搜索挑选
- 主题：站立、下班、摸鱼、喝水、睡觉
- 数量：每个主题 5-10 张，总计 20-30 张
- 格式：JPG / GIF / PNG

**挑选标准：**
- 搞笑、轻松、不冒犯
- 清晰度足够（不要糊图）
- 避免带广告水印

---

## 3. 指令清单

| 指令 | 别名 | 说明 |
|------|------|------|
| `/提醒 开` | `/reminder on` | 为本群开启定时提醒 |
| `/提醒 关` | `/reminder off` | 为本群关闭定时提醒 |

---

## 4. 实施清单

**一次性完成，无需分期。**

| ID | 任务 |
|---|---|
| 1 | 创建数据表 `reminder_enabled_groups` + migration |
| 2 | 实现 `/提醒 开/关` 指令处理器 |
| 3 | 配置概率池 + 注册 5 个定时任务到 `core.scheduler` |
| 4 | 实现图片发送逻辑（复用 `/吃什么` 的 base64 编码方案） |
| 5 | 挑选梗图素材（20-30 张），存放到 `resources/reminders/` |
| 6 | 编写单元测试（概率触发逻辑 + 数据库操作） |

---

## 5. 可选扩展（基础版不做）

| 功能 | 说明 |
|------|------|
| 节日彩蛋 | 周五 18:00 触发概率 100%，文案换"周末快乐！" |
| 自定义时段 | 管理员配置触发时间 |
| 自定义文案 | 群友投稿提醒语 |
| 天气联动 | 下雨时提示"记得带伞" |

---

## 6. 约定与限制

- **轻量工具**，不接入游戏框架（`GameBase`），不入 `docs/10-roadmap.md`
- **不做 CLI 模拟**（定时任务无法在 CLI 里测试，本地测试用单元测试覆盖）
- **群消息通知**，不支持私聊
- **零经济交互**，不涉及 coin/score
- **静默失败**，发送失败只记日志，不影响其他群

---

## 7. 测试策略

### 单元测试

- 概率逻辑：多次调用验证触发率接近配置值
- 开关逻辑：开启/关闭后查询状态正确
- 消息构造：文字/图片消息格式正确

### 手动测试

- 本地修改 cron 为 `* * * * *`（每分钟）快速验证
- 检查群里收到消息
- 检查图片能正常显示

---

## 8. 部署注意事项

- 确保服务器时区正确（中国 UTC+8）
- 图片资源一起打包到 Docker 镜像或挂载到容器
- 首次上线建议先在测试群验证，避免打扰用户

---

**END**
