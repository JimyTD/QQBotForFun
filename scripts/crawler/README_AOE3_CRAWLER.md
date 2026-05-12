# AoE3:DE 兵种数据爬虫 - 操作指南

## 当前状态

- ✅ 爬虫脚本已完成：`scripts/crawler/aoe3_wiki_crawler.py`
- ✅ 已有占位数据：`seeds/aoe3/units.json`（67KB，手动估算值，**不精确**）
- ❌ 当前环境无法访问外网（Fandom Wiki / GitHub），需要换有网络的环境执行

## 目标

从 Fandom Wiki 爬取精确的 AoE3:DE 兵种数据，替换现有的估算数据。

## 快速开始（换环境后）

### 1. 安装依赖

```bash
pip install beautifulsoup4 lxml httpx
```

### 2. 测试连通性

```bash
python scripts/crawler/find_aoe3_data.py
```

确认输出中 `Fandom Wiki API` 显示 `[OK]` 即可。

### 3. 如果需要代理

```bash
# Windows CMD
set HTTPS_PROXY=http://127.0.0.1:7890
set HTTP_PROXY=http://127.0.0.1:7890

# Linux/Mac
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

### 4. 试跑（抓5个单位测试）

```bash
python scripts/crawler/aoe3_wiki_crawler.py --limit 5
```

检查 `seeds/aoe3/units.json` 看数据是否正确。

### 5. 全量爬取

```bash
python scripts/crawler/aoe3_wiki_crawler.py --force
```

- `--force`：覆盖已有数据重新爬取
- 不加 `--force`：断点续跑（跳过已有单位）
- 每次请求间隔 1 秒（礼貌爬取），全量约需 10-15 分钟

### 6. Windows 一键脚本

双击 `scripts/crawler/run_aoe3_crawler.bat` 即可（会先测试连通性再爬取）。

## 数据覆盖范围

爬虫覆盖以下分类：
- 步兵 (infantry)
- 骑兵 (cavalry)
- 炮兵 (artillery)
- 海军 (naval_vessels)
- 雇佣兵 (mercenaries)
- 原住民战士 (native_warriors)
- 英雄 (heroes)

## 输出格式

```json
{
  "id": "musketeer_age_of_empires_iii",
  "name_en": "Musketeer (Age of Empires III)",
  "name": "火枪手",
  "wiki_url": "https://ageofempires.fandom.com/wiki/...",
  "hp": 150,
  "attack_ranged": 23,
  "attack_melee": 13,
  "range": 12,
  "speed": 4.0,
  "cost": {"food": 75, "gold": 25},
  "pop": 1,
  "type": ["Heavy Infantry", "Gunpowder Infantry"],
  "multipliers": [{"vs": "Cavalry", "value": 3.0}],
  "civs": ["British", "French", ...],
  "age": "Age III"
}
```

## 备选方案：游戏文件提取（最精确）

如果有 AoE3:DE 安装目录，可直接解析游戏数据文件：

```
Steam/steamapps/common/AoE3DE/resources/Data/protoy.xml
```

这是明文 XML，包含所有单位的精确数值。需要时可以写一个 `protoy.xml` 解析器。

## 文件清单

| 文件 | 用途 |
|------|------|
| `scripts/crawler/aoe3_wiki_crawler.py` | 主爬虫脚本 |
| `scripts/crawler/find_aoe3_data.py` | 连通性测试脚本 |
| `scripts/crawler/detect_proxy.py` | 代理检测脚本 |
| `scripts/crawler/run_aoe3_crawler.bat` | Windows 一键运行 |
| `scripts/crawler/test_aoe3_api.py` | API 格式测试 |
| `seeds/aoe3/units.json` | 输出数据文件 |
