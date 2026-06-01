# 10 · 路线图与版本变更

- **Status**: Stable（项目已进入稳定维护期）
- **Last Updated**: 2026-05-26
- **Owner**: @owner

> 本文件记录项目的演进历程和当前状态。
> 初期的"从零搭建"清单已全部完成，现转为版本变更日志 + 未来方向。

## 0. 项目状态

项目已完成 MVP 框架搭建，进入**稳定运行 + 增量迭代**阶段：

- ✅ 完整的分层架构（Core / Games / Tools / Plugins）
- ✅ 4 款游戏上线（海龟汤 / 趣味问答 / 帝国3斗蛐蛐 / 红警2斗蛐蛐）
- ✅ 5 款工具上线（签到 / 今天吃什么 / 上班提醒 / 联网搜索 / 游戏王查卡）
- ✅ CLI 测试器与 QQ Bot 1:1 对齐
- ✅ Docker 生产部署稳定运行
- ✅ 完整文档体系（13 篇专题 + ADR + 游戏设计 + 工具设计 + 运维手册）

## 1. 文档清单

| ID | 文件 | 状态 |
|---|---|---|
| D1 | `README.md` | ✅ |
| D2 | `docs/01-architecture.md` | ✅ |
| D3 | `docs/02-tech-stack.md` | ✅ |
| D4 | `docs/03-core-api.md` | ✅ |
| D5 | `docs/04-game-development.md` | ✅ |
| D6 | `docs/05-deployment.md` | ✅ |
| D7 | `docs/06-configuration.md` | ✅ |
| D8 | `docs/07-database-schema.md` | ✅ |
| D9 | `docs/08-llm-integration.md` | ✅ |
| D10 | `docs/09-conventions.md` | ✅ |
| D11 | `docs/10-roadmap.md` | ✅ 本文件 |
| D12 | `docs/11-ui-style.md` | ✅ |
| D13 | `docs/12-local-testing.md` | ✅ |
| D14 | `docs/13-cli-bot-parity.md` | ✅ |
| D15 | `docs/ops-guide.md` | ✅ |
| D16 | `docs/commands.md` | ✅ |
| D17 | `docs/games/*.md` | ✅ 海龟汤 / 趣味问答 / 帝国3 / 红警2 / 群峦求生(设计中) |
| D18 | `docs/tools/*.md` | ✅ 签到 / 今天吃什么 / 上班提醒 / 联网搜索 / 游戏王查卡 |
| D19 | `docs/adr/0001~0003` | ✅ |

## 2. 当前目录结构

```
QQBotForFun/
├─ .env.example
├─ .gitignore
├─ pyproject.toml
├─ uv.lock
├─ README.md
├─ LICENSE
├─ Dockerfile
├─ docker-compose.yml                   (prod)
├─ docker-compose.dev.yml               (本地 NapCat)
├─ alembic.ini
├─ migrations/
│  ├─ env.py
│  └─ versions/
├─ docs/
│  ├─ 01~13 专题文档
│  ├─ ops-guide.md / commands.md
│  ├─ games/                            (游戏设计文档)
│  ├─ tools/                            (工具设计文档)
│  ├─ adr/                              (架构决策记录)
│  └─ test-runs/                        (验收流水归档)
├─ config/
│  ├─ llm.yaml
│  └─ searxng/
├─ scripts/
│  ├─ play_cli.py                       (CLI 统一入口)
│  ├─ cli_adapters/                     (各游戏/工具 CLI 适配器)
│  ├─ crawler/                          (数据爬取/解析脚本)
│  ├─ seed_*.py / generate_*.py         (种子数据 & 生成脚本)
│  ├─ aoe3_battle_sim.py / ra2_battle_sim.py  (模拟器独立运行)
│  └─ test_*_variety.py                 (LLM 产出验收脚本)
├─ seeds/
│  ├─ aoe3/                             (帝国3单位数据 + i18n)
│  ├─ trivia_bank/                      (趣味问答题库 6 类)
│  ├─ turtle_soup.json                  (海龟汤题库)
│  ├─ turtle_soup_facts.json
│  └─ foods.json                        (今天吃什么菜品库)
├─ resources/
│  ├─ aoe3/                             (帝国3图标)
│  ├─ ra2/                              (红警2图标)
│  ├─ checkin/                          (签到素材)
│  ├─ foods/                            (菜品图片)
│  └─ reminders/                        (提醒素材)
├─ vendor/
│  └─ (OpenRA RA2 数据)
├─ src/
│  ├─ bot.py                            (入口)
│  ├─ settings.py
│  ├─ core/
│  │  ├─ errors.py / types.py
│  │  ├─ storage.py / user.py / session.py
│  │  ├─ economy.py / permission.py / scheduler.py
│  │  ├─ llm.py / render.py / game_base.py
│  │  └─ ...
│  ├─ plugins/
│  │  ├─ core_commands/                 (基础命令)
│  │  ├─ game_launcher/                 (游戏启动器)
│  │  ├─ admin/                         (管理员命令)
│  │  ├─ aoe3/                          (帝国3查询插件)
│  │  ├─ message_router.py             (消息路由)
│  │  ├─ games/
│  │  │  ├─ turtle_soup/
│  │  │  ├─ trivia/
│  │  │  ├─ aoe3_battle/
│  │  │  └─ ra2_battle/
│  │  └─ tools/
│  │     ├─ ask_ai/
│  │     ├─ checkin/
│  │     ├─ food/
│  │     ├─ reminder/
│  │     ├─ web_search/
│  │     └─ yugioh_card/
│  └─ testing/
│     └─ harness.py
├─ tests/
│  ├─ conftest.py
│  ├─ core/
│  ├─ games/
│  ├─ tools/
│  └─ eval/
└─ napcat/
   └─ config.example.json
```

## 3. 初期实施清单（已全部完成）

> 以下为项目从零搭建时的阶段清单，所有项目均已完成，保留作为历史记录。

- ✅ **阶段 A** · 文档补齐（13 篇专题 + 3 篇 ADR）
- ✅ **阶段 B** · 脚手架（pyproject.toml / .env / settings / alembic）
- ✅ **阶段 C** · Core 层（errors / types / storage / user / session / economy / permission / scheduler / llm / render / game_base）
- ✅ **阶段 D** · 系统插件（core_commands / game_launcher / admin / message_router）
- ✅ **阶段 E** · 海龟汤游戏（models / prompts / puzzle_service / game / commands）
- ✅ **阶段 F** · 数据与脚本（seeds / seed scripts / generate scripts / alembic migration）
- ✅ **阶段 G** · 部署（Dockerfile / docker-compose / napcat config）
- ✅ **阶段 H** · 测试（harness / core 单测 / 海龟汤集成测试）
- ✅ **阶段 I** · 收尾（README 完善 / 全清单自查）

## 4. 明确不做的范围

- 段位 / 积分榜 UI（仅全文本 `/榜` 指令，不做图片榜单、段位系统）
- Web 管理后台
- 真人出题模式
- Sentry / Prometheus 监控
- CI/CD Workflow（可留示例文件但不默认启用）
- HTML→图片渲染（全文本 UI）
- Pillow 绘图
- 美术资源（Logo / 插画 / 字体文件）

## 5. 版本变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版基线：完整框架 + 海龟汤 |
| v1.1 | 2026-04-30 | `economy` 追加榜单 helper；`/榜` 指令；`score` 跨游戏积分 |
| v1.2 | 2026-04-30 | 第二款游戏 `trivia`（趣味问答）上线 |
| v1.3 | 2026-05-06 | `trivia` 题库化重构：650 道 × 2 套线索，运行时不调 LLM |
| v1.4 | 2026-05-09 | 工具层上线：签到 / 今天吃什么 / 上班提醒 |
| v1.5 | 2026-05-11 | 游戏王查卡工具上线 |
| v1.6 | 2026-05-15 | 帝国3斗蛐蛐上线（一维自研模拟器） |
| v1.7 | 2026-05-18 | 红警2斗蛐蛐上线（二维 OpenRA 数据） |
| v1.8 | 2026-05-26 | 联网搜索工具上线；文档体系清理与更新 |

## 6. 未来方向（非承诺）

- 群峦求生（`terra_survival`）：TFC/GT 风格持久化沙盘，设计文档已完成，待启动开发
- AOE3 斗蛐蛐 · 二维 AOE 精确几何（暂缓）：阵线宽度 + 兵种碰撞体积（footprint），让炮兵溅射不再每发打满。需 `protoy.xml` 解包体积字段 + formation/aoe 模块重写，工程量大收益有限，当前一维模型够用
- ~~AOE3 tooltip 解包与展示~~ ✅（2026-05-27）
- 海龟汤 Agent 优化（持续迭代 prompt 质量）
