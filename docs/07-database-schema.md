# 07 · 数据库设计

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

## 1. 总则

1. **ORM**：SQLAlchemy 2.0 async
2. **迁移**：Alembic
3. **开发库**：SQLite（`./data/bot.db`）
4. **生产库**：PostgreSQL 16
5. **表名前缀**：
   - 公共表：无前缀（`user`, `economy_balance` 等）
   - 游戏专属表：**强制** `game_<game_id>_`（如 `game_turtle_soup_puzzle`）
6. **所有表**均有 `id` 主键 + `created_at` + `updated_at`（除显式无需）

## 2. 命名约定

| 对象 | 规则 |
|---|---|
| 表名 | `snake_case`，单数形式（`user` 不用 `users`） |
| 字段 | `snake_case` |
| 外键 | `<ref_table>_id` |
| 索引 | `ix_<table>_<col>` |
| 唯一索引 | `ux_<table>_<col>` |

## 3. 公共表

### 3.1 `user` — 用户档案

| 字段 | 类型 | 说明 |
|---|---|---|
| `qq_id` | BigInt PK | QQ 号 |
| `nickname` | String(64) | 最近一次见到的昵称（缓存） |
| `avatar_url` | String(256) | 头像 URL |
| `created_at` | Timestamp | 首次见到 |
| `updated_at` | Timestamp | 最近活跃 |

索引：`ix_user_updated_at`

### 3.2 `economy_balance` — 货币余额

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BigInt PK | |
| `qq_id` | BigInt FK | → user |
| `currency` | String(32) | `coin` / `ticket` / ... |
| `balance` | BigInt | 余额，非负 |
| `updated_at` | Timestamp | |

唯一：`ux_economy_balance_qq_currency (qq_id, currency)`

### 3.3 `economy_tx` — 货币流水

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BigInt PK | |
| `qq_id` | BigInt | |
| `currency` | String(32) | |
| `delta` | BigInt | 正数为入账，负数为出账 |
| `balance_after` | BigInt | 事后余额（冗余便于审计） |
| `reason` | String(128) | 必填 |
| `ref_type` | String(32) | `game/admin/transfer/...` |
| `ref_id` | String(64) | 关联业务 ID |
| `created_at` | Timestamp | |

索引：`ix_economy_tx_qq_created`、`ix_economy_tx_ref`

### 3.4 `economy_item` — 道具库存

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BigInt PK | |
| `qq_id` | BigInt | |
| `item_id` | String(64) | |
| `count` | Int | 非负 |
| `updated_at` | Timestamp | |

唯一：`ux_economy_item_qq_item (qq_id, item_id)`

### 3.5 `game_session` — 游戏对局（跨游戏统一记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | String(32) PK | 短 UUID |
| `game_id` | String(32) | `turtle_soup` 等 |
| `group_id` | BigInt | 所在群 |
| `host_id` | BigInt | 开局者 |
| `players` | JSON | QQ 列表 |
| `state` | JSON | 序列化的 `ctx.state`（用于恢复） |
| `status` | String(16) | `active/ended` |
| `end_reason` | String(32) \| null | `completed/timeout/aborted/error` |
| `started_at` | Timestamp | |
| `ended_at` | Timestamp \| null | |

索引：
- `ix_game_session_group_status (group_id, status)`
- `ix_game_session_game_started (game_id, started_at)`

### 3.6 `cooldown` — 冷却记录（Redis 不可用时的 fallback）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BigInt PK | |
| `scope_key` | String(128) | 例如 `user:10001:cmd_play` |
| `expires_at` | Timestamp | |

唯一：`ux_cooldown_scope (scope_key)`

> 生产环境走 Redis，此表只在 dev 模式使用。

### 3.7 `admin_role` — 管理员角色

| 字段 | 类型 | 说明 |
|---|---|---|
| `qq_id` | BigInt PK | |
| `role` | String(16) | `owner/admin` |
| `granted_by` | BigInt | |
| `created_at` | Timestamp | |

## 4. 海龟汤游戏表

### 4.1 `game_turtle_soup_puzzle` — 题库

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BigInt PK | |
| `title` | String(128) | |
| `category` | String(32) | `日常/悬疑/温情/奇幻` |
| `surface` | Text | 汤面 |
| `truth` | Text | 汤底 |
| `key_clues` | JSON | 关键线索列表 |
| `source` | String(16) | `builtin/llm_generated` |
| `difficulty` | Int | 1-5 |
| `play_count` | BigInt | 已出场次数 |
| `win_count` | BigInt | 被猜中次数 |
| `created_at` | Timestamp | |

索引：
- `ix_game_turtle_soup_puzzle_source`
- `ix_game_turtle_soup_puzzle_play_count`

### 4.2 `game_turtle_soup_session` — 对局

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | String(32) PK FK | → game_session |
| `puzzle_id` | BigInt FK | → game_turtle_soup_puzzle |
| `question_count` | Int | |
| `winner_id` | BigInt \| null | |

### 4.3 `game_turtle_soup_question` — 提问记录

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BigInt PK | |
| `session_id` | String(32) FK | |
| `asker_id` | BigInt | |
| `question` | Text | |
| `verdict` | String(16) | `yes/no/irrelevant/key/claim_detected` |
| `hint` | Text \| null | |
| `asked_at` | Timestamp | |

索引：`ix_game_turtle_soup_question_session_asked`

## 5. 迁移策略

### 5.1 Alembic 结构
```
migrations/
├─ env.py               # 从 core.storage 导入所有 Base 的 metadata
├─ script.py.mako
└─ versions/
   ├─ 0001_init.py      # 公共表 + 海龟汤表（首次交付合并到一起）
   └─ ...
```

### 5.2 新增游戏时
```bash
# 游戏自己声明 models.py 后：
alembic revision --autogenerate -m "add game_xxx tables"
alembic upgrade head
```

### 5.3 破坏性变更
- 字段改名：新增→双写→迁移→删除旧（分 3 次 release）
- 表删除：加 deprecated 注释至少一个版本后再删

## 6. 外键策略

- 核心：`economy_balance.qq_id → user.qq_id`，游戏表 → 公共表均加外键
- SQLite 需要 `PRAGMA foreign_keys=ON`，在 storage 启动代码里设置

## 7. JSON 字段使用原则

可用 JSON 类型的场景：
- ✅ 动态结构（`game_session.state`）
- ✅ 小规模列表（`puzzle.key_clues` 3-6 条）
- ❌ 需要查询/索引其子项的结构（应拆字段或拆表）

## 8. 性能考虑

本项目规模预计：
- 用户：百-千级
- 对局：日均几十到几百
- 提问：日均几百到几千
- **SQLite 在 dev 完全够用**，PostgreSQL 可支撑到日均十万级

无需分库分表。

## 9. 备份与恢复

- 生产：定期 `pg_dump` 到对象存储（部署文档详述）
- dev：SQLite 文件直接拷贝
- 恢复后，活跃 `game_session` 会被 `core.game_base.recover_active_sessions()` 自动加载

## 10. 变更日志
| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
