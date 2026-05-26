# 免费 / 低成本 LLM API 厂商调研

- **Status**: Living doc
- **Last Updated**: 2026-05-26
- **用途**: 选型参考；政策变动频繁，接入前务必看官网最新公告

> 本项目 bot **在线**用的配置以 `config/llm.yaml` 为准。  
> 跑 ping：`uv run --no-sync python scripts/benchmark_llm.py`

---

## 1. 本项目当前策略（2026-05-26）

| 类型 | 选择 | 原因 |
|------|------|------|
| 海龟汤 judge / claim | **LongCat-Flash-Chat** | golden eval Soft 90.7%、F1 87.5%，同 Key 内最优 |
| 查资料（web_search / ask_ai） | **LongCat-Flash-Lite** | ping 最快，5000 万 token/天 |
| 低频 / 出题 | **智谱 glm-4-flash-250414** | 官方免费档，JSON 出题稳定 |
| 不再使用 | glm-4-flash、flashx、Thinking、硅基流动 | 判题更差或 JSON 不可用；flashx 付费需余额 |

---

## 2. 国内平台（值得盯的活动）

### 已在用

| 平台 | 注册 | 免费力度 | 代表模型 | OpenAI 兼容 |
|------|------|----------|----------|-------------|
| [智谱 BigModel](https://open.bigmodel.cn/) | 手机 | GLM-4-Flash-250414 **免费**；新用户常有 2000 万 token 包 | flash-250414、4.7-flash | ✅ |
| [美团 LongCat](https://longcat.chat/platform/) | 手机 | **Lite 5000 万/天**；Chat 等共享 500 万/天 | Flash-Lite、Flash-Chat、2.0-Preview | ✅ |

### 可试、未接入

| 平台 | 免费力度（网传/官网，请自验） | 适合场景 | 备注 |
|------|------------------------------|----------|------|
| [阿里云百炼](https://bailian.console.aliyun.com/) | 新用户各模型 100 万 token，合计 **7000 万+**（约 90 天） | Qwen3 全系列、DeepSeek、GLM、Kimi | 需阿里云账号 |
| [DeepSeek](https://platform.deepseek.com/) | 新用户 **500 万 token**（约 30 天） | V3.2 / R1，极低价付费 | `api.deepseek.com/v1` |
| [ModelScope 魔搭](https://modelscope.cn/) | **2000 次/天**（推理类） | 多模型体验 | 深度推理限 200 次/天 |
| [Moonshot Kimi](https://platform.moonshot.cn/) | 低速率免费档（约 3 RPM） | 256K 长文 | 不适合 QQ 群高频 |
| [商汤 SenseNova](https://platform.sensenova.cn/) | 首月每 **5 小时 1500 次** Token Plan | 多模态、Agent | 2026 新推，活动期 |
| [腾讯混元](https://cloud.tencent.com/product/hunyuan) | 新用户约 **100 万 token**（1 年） | 混元系列 | 常与其他云活动打包 |
| [火山引擎豆包](https://www.volcengine.com/product/doubao) | 新用户测试额度 | 多模态 | 需实名 |
| [讯飞星火](https://xinghuo.xfyun.cn/) | 新用户测试额度 | 联网、多模态 | 需申请 |
| [小米 MiMo](https://platform.xiaomimimo.com/) | 百万亿 token 激励计划（申请制） | 编程向 | 2026 新平台 |
| [InternLM 书生](https://chat.intern-ai.org.cn/) | 约 10 RPM | InternVL 等 | 密钥约 6 个月 |

### 已放弃 / 慎用

| 平台 | 说明 |
|------|------|
| 硅基流动 | 项目 2026-04 额度耗尽，已从代码与配置移除 |
| 智谱 glm-4-flashx | **付费**，无余额报 1113 |
| OpenRouter 免费档 | ~50 次/天，适合个人玩不适合群 bot |

---

## 3. 国外 / 聚合（国内访问需自测）

| 平台 | 免费力度 | 说明 |
|------|----------|------|
| [OpenRouter](https://openrouter.ai/) | 多模型 `:free` 后缀，20 RPM / 50 RPD | 适合试验，不稳定 |
| [Groq](https://console.groq.com/) | Llama 等高速推理免费档 | 国内延迟看网络 |
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/) | 每日神经元配额 | 边缘部署友好 |
| [GitHub Models](https://github.com/marketplace/models) | Copilot 用户有限免费 | 非生产 |
| [NVIDIA NIM](https://build.nvidia.com/) | 部分模型免费推理 | ToS 偏评估用途 |

聚合代理（自建）：[FreeLLMAPI](https://github.com/mervindublin/FreeLLMAPI) 等把多厂商免费档拼成一个 OpenAI 端点——适合个人实验，**不建议**直接上 QQ 生产。

---

## 4. 选型原则（QQ 群 bot）

1. **判题（judge/claim）** → 先跑 `eval_judge_compare.py`，Soft/F1 过线再上生产（当前：**LongCat-Flash-Chat**）
2. **高频非判题（查资料）** → 日额度大 + 延迟低（当前：**LongCat-Flash-Lite**）
3. **只比有意义候选** → benchmark / eval 脚本不含已知更差或 ping 不通的模型；未配 Key 的 challenger 静默跳过
4. **免费≠无限** → 注意 RPM、5 小时窗口、每日清零
5. **活动会过期** → 本表仅作线索；换厂商前 ping 一轮

---

## 5. 实测判题质量（2026-05-26，`eval_judge_compare.py` · 14 golden · prompt v1.2）

仅列出**有意义候选**（生产相关 + 已配 Key 的 challenger）。老模型 / JSON 不可用 / 当日 ping 失败的不在此表。

| 模型 | 免费 | Strict | Soft | **F1** | P50 | 结论 |
|------|------|--------|------|--------|-----|------|
| **LongCat-Flash-Chat** | ✅ 500万/天 | **78.6%** | **90.7%** | **87.5%** | 813ms | **生产 judge/claim** |
| LongCat-Flash-Lite | ✅ 5000万/天 | 71.4% | 81.4% | 75.0% | 484ms | 查资料；judge 备选 |
| glm-4-flash-250414 | ✅ | 71.4% | 81.4% | 83.8% | 921ms | 出题 / 兜底 |

---

## 6. 变更日志

| 日期 | 变更 |
|------|------|
| 2026-05-26 | judge/claim 切 LongCat-Flash-Chat；查资料仍 Lite；eval 仅比有意义候选 |
| 2026-05-26 | 初版；judge/claim/web_search 切 LongCat-Flash-Lite；移除硅基引用 |
