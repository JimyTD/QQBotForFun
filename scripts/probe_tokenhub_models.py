"""TokenHub 模型探针 —— 一次跑出各档的「脾气」，用于回填 `core.llm._MODEL_QUIRKS`。

背景：不同模型对 `temperature` / `thinking` / `response_format` 的接受度不一样，
不迁就就是整档 400、白白降级（见 docs/08-llm-integration.md §2、§4.2）。
凭猜测填 quirks 会引入更多错误，所以这里实测。

用法：
    uv run python scripts/probe_tokenhub_models.py --list           # 只列在线模型，不消耗额度
    uv run python scripts/probe_tokenhub_models.py                  # 测 llm.yaml 里出现的全部 tokenhub 档
    uv run python scripts/probe_tokenhub_models.py --models a,b,c   # 只测指定模型

⚠️ 除 `--list` 外都会**真实调用并消耗 TokenHub 免费额度**。
   每模型最多 3 次极短调用（max_tokens=8）；某档一旦判定额度耗尽，自动跳过后续探测。
"""

from __future__ import annotations

import argparse
import asyncio
import io
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402
import yaml  # noqa: E402

from src.settings import get_settings  # noqa: E402

#: 极短 prompt —— 探测只关心「接不接受这个参数」，不关心答得好不好。
PLAIN_MESSAGES = [{"role": "user", "content": "回复两个字：可用"}]
JSON_MESSAGES = [{"role": "user", "content": '只输出 JSON：{"ok": true}'}]

TIMEOUT = 60.0


@dataclass
class ProbeResult:
    """单个模型的探测结果。"""

    model: str
    state: str = "?"  # ok / quota / auth / unavailable / bad_request / network
    http_status: int | None = None
    #: 默认参数下的延迟（可能带着思考）
    latency_ms: int | None = None
    #: 发 thinking=disabled 之后的延迟 —— 这才是生产实际表现的参考值
    latency_nothink_ms: int | None = None
    error: str = ""
    #: 是否接受 {"type": "json_object"}
    json_ok: bool | None = None
    #: 是否接受 thinking 字段（False = 发了就 400，应改为完全不发）
    thinking_ok: bool | None = None
    #: 返回体里是否有 reasoning_content（说明真的在思考）
    reasoning: bool = False
    #: temperature 相关的观察（如「只接受 0.6」）
    temperature_note: str = ""
    #: 建议回填到 _MODEL_QUIRKS 的片段
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.state == "ok"


# ---------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------
def tokenhub_models_from_config() -> list[str]:
    """从 config/llm.yaml 里按出现顺序取出所有 `tokenhub:<model>`（去重）。"""
    path = Path(get_settings().llm_config_path)
    if not path.exists():
        print(f"⚠️ 找不到配置：{path}")
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    seen: set[str] = set()
    out: list[str] = []
    for block in (data.get("scenes") or {}).values():
        if not isinstance(block, dict):
            continue
        for item in block.get("chain") or []:
            if isinstance(item, str) and item.startswith("tokenhub:"):
                model = item.split(":", 1)[1].strip()
                if model and model not in seen:
                    seen.add(model)
                    out.append(model)
    return out


# ---------------------------------------------------------------------
# 单次调用
# ---------------------------------------------------------------------
async def _call(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    payload: dict[str, Any],
) -> tuple[int, Any, int]:
    """返回 (http_status, body, latency_ms)；网络异常返回 status=0。"""
    t0 = time.monotonic()
    try:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    except Exception as e:  # noqa: BLE001
        return 0, str(e), int((time.monotonic() - t0) * 1000)
    ms = int((time.monotonic() - t0) * 1000)
    try:
        return resp.status_code, resp.json(), ms
    except Exception:  # noqa: BLE001
        return resp.status_code, resp.text, ms


def _classify(status: int, body: Any) -> tuple[str, str]:
    """粗判结果类别与摘要错误信息（与 core.llm 的分类保持同一套语义）。"""
    text = body if isinstance(body, str) else str(body)
    low = text.lower()
    if status == 0:
        return "network", text[:200]
    if status == 200:
        return "ok", ""
    if "401006" in text or "endpoint is inactive" in low:
        return "transient", text[:200]
    if status == 402 or "402" in text[:80]:
        return "quota", text[:200]
    if status == 429:
        return "rate_limited", text[:200]
    if status in (401, 403):
        return "auth", text[:200]
    if status == 404:
        return "unavailable", text[:200]
    if status == 400:
        return "bad_request", text[:200]
    return "error", text[:200]


def _content_of(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    try:
        return (body["choices"][0]["message"].get("content") or "")
    except Exception:  # noqa: BLE001
        return ""


def _has_reasoning(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    try:
        msg = body["choices"][0]["message"]
    except Exception:  # noqa: BLE001
        return False
    return bool(msg.get("reasoning_content"))


# ---------------------------------------------------------------------
# 单模型探测
# ---------------------------------------------------------------------
async def probe_model(
    client: httpx.AsyncClient, url: str, key: str, model: str, delay: float
) -> ProbeResult:
    r = ProbeResult(model=model)
    base_temp = 0.1

    # --- 1. 基础可用性 / 默认延迟 / temperature 边界 ---
    status, body, ms = await _call(
        client,
        url,
        key,
        {"model": model, "messages": PLAIN_MESSAGES, "max_tokens": 8, "temperature": base_temp},
    )
    state, err = _classify(status, body)
    r.http_status, r.error, r.latency_ms = status, err, ms

    if state == "ok":
        r.reasoning = _has_reasoning(body)
        if not _content_of(body).strip():
            r.error = "返回内容为空"
    elif state == "bad_request" and "temperature" in err.lower():
        # 该档对 temperature 有取值限制 —— 逐值试探（kimi-k2.5 实测只接受 1.0）
        r.temperature_note = "拒绝 temperature=0.1"
        found = False
        for candidate in (0.6, 1.0):
            await asyncio.sleep(delay)
            s2, b2, ms2 = await _call(
                client,
                url,
                key,
                {
                    "model": model,
                    "messages": PLAIN_MESSAGES,
                    "max_tokens": 8,
                    "temperature": candidate,
                },
            )
            if s2 == 200:
                base_temp = candidate
                found = True
                r.extra["temperature"] = candidate
                r.temperature_note = f"只接受 temperature={candidate}"
                r.latency_ms = ms2
                r.reasoning = _has_reasoning(b2)
                break
        if not found:
            r.state = "bad_request"
            return r
    else:
        r.state = state
        return r

    r.state = "ok"

    # --- 2. thinking={"type":"disabled"}：字段接受度 + 关掉思考后的真实延迟 ---
    await asyncio.sleep(delay)
    s, b, ms = await _call(
        client,
        url,
        key,
        {
            "model": model,
            "messages": PLAIN_MESSAGES,
            "max_tokens": 8,
            "temperature": base_temp,
            "thinking": {"type": "disabled"},
        },
    )
    r.thinking_ok = s == 200
    if r.thinking_ok:
        r.latency_nothink_ms = ms
        if _has_reasoning(b):
            # 发了 disabled 仍返回思考内容 → 该字段实则关不掉，不如干脆不发
            r.extra["no_thinking"] = True
            r.temperature_note = (r.temperature_note + "；thinking 关不掉").strip("；")
    else:
        r.extra["no_thinking"] = True
        r.temperature_note = (r.temperature_note + "；thinking 字段被拒").strip("；")

    # --- 3. response_format={"type":"json_object"} ---
    await asyncio.sleep(delay)
    s, b, _ = await _call(
        client,
        url,
        key,
        {
            "model": model,
            "messages": JSON_MESSAGES,
            "max_tokens": 32,
            "temperature": base_temp,
            "response_format": {"type": "json_object"},
        },
    )
    r.json_ok = s == 200
    if not r.json_ok:
        r.error = (r.error + f" | json_mode: {_classify(s, b)[1]}").strip(" |")

    return r


def read_tokenhub_base_url(config_path: Path) -> str:
    """从 llm.yaml 里抠出 tokenhub 的 base_url；读不到就用官方广州站地址。

    刻意做成同步函数 —— 在 async 里直接调 Path 的阻塞 IO 会触发 ASYNC240。
    """
    default = "https://tokenhub.tencentmaas.com/v1"
    if not config_path.exists():
        return default
    text = config_path.read_text(encoding="utf-8")
    m = re.search(r"tokenhub:\s*\n(?:.*\n)*?\s*base_url:\s*(\S+)", text)
    return m.group(1).strip().rstrip("/") if m else default


async def list_models(url: str, key: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        print(f"⚠️ /v1/models 返回结构不符合预期，原始响应片段：{str(payload)[:500]}")
        return []
    return [it for it in items if isinstance(it, dict)]


# ---------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------
def print_table(results: list[ProbeResult]) -> None:
    print()
    print(
        f"{'模型':<34} {'状态':<13} {'默认延迟':>10} {'关思考后':>10}  "
        f"{'JSON':<6} {'thinking':<9} 备注"
    )
    print("-" * 130)
    for r in results:
        plain = f"{r.latency_ms}ms" if r.latency_ms is not None else "-"
        nothink = f"{r.latency_nothink_ms}ms" if r.latency_nothink_ms is not None else "-"
        json_ok = {True: "✓", False: "✗", None: "-"}[r.json_ok]
        think_ok = {True: "✓", False: "✗", None: "-"}[r.thinking_ok]
        note = r.temperature_note
        if r.reasoning:
            note = (note + "；默认带思考").strip("；")
        if r.state != "ok" and r.error:
            note = (note + "；" + r.error[:60]).strip("；")
        print(
            f"{r.model:<34} {r.state:<13} {plain:>10} {nothink:>10}  "
            f"{json_ok:<6} {think_ok:<9} {note}"
        )


def print_quirks(results: list[ProbeResult]) -> None:
    interesting = [r for r in results if r.usable and r.extra]
    print()
    print("=" * 118)
    if not interesting:
        print("结论：所有可用档都吃默认参数，_MODEL_QUIRKS 无需新增条目。")
        return
    print("建议回填到 src/core/llm.py 的 _MODEL_QUIRKS（只列需要特殊照顾的档）：")
    print()
    print("_MODEL_QUIRKS: dict[str, dict[str, Any]] = {")
    for r in interesting:
        print(f"    {r.model!r}: {r.extra!r},")
    print("}")
    print()
    print("⚠️ 回填前请人工确认：探测只覆盖「参数是否被接受」，不代表判定质量。")


def print_summary(results: list[ProbeResult], online: set[str] | None) -> None:
    ok = [r for r in results if r.usable]
    quota = [r for r in results if r.state == "quota"]
    gone = [r for r in results if r.state == "unavailable"]
    print()
    print("=" * 118)
    print(f"可用 {len(ok)} / 共测 {len(results)}；额度耗尽 {len(quota)}；已下线 {len(gone)}")
    if online is not None:
        offline_cfg = [r.model for r in results if r.model not in online]
        if offline_cfg:
            print(f"不在 /v1/models 在线清单里的档（{len(offline_cfg)}）：{', '.join(offline_cfg)}")
    if quota:
        print(f"额度已耗尽的档：{', '.join(r.model for r in quota)}")
        print("→ 这些都是各自独立的池，耗尽即永久失效，链上会自动跳过。")


# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------
async def main() -> None:
    parser = argparse.ArgumentParser(description="TokenHub 模型探针")
    parser.add_argument("--models", help="逗号分隔，只测这些模型（默认取 llm.yaml 里的 tokenhub 档）")
    parser.add_argument("--list", action="store_true", help="只列在线模型，不发起 chat 调用")
    parser.add_argument("--delay", type=float, default=0.6, help="相邻调用间隔秒数（默认 0.6）")
    args = parser.parse_args()

    settings = get_settings()
    key = settings.tokenhub_api_key.strip()
    if not key:
        print("❌ TOKENHUB_API_KEY 为空 —— 请先在 .env 里配好。")
        return

    base_url = read_tokenhub_base_url(Path(settings.llm_config_path))

    online: set[str] | None = None
    try:
        items = await list_models(base_url + "/models", key)
        online = {str(it.get("id")) for it in items if it.get("id")}
        print(f"✅ /v1/models 在线 {len(online)} 个模型")
        if args.list:
            for it in sorted(items, key=lambda x: str(x.get("id"))):
                print(f"  {it.get('id'):<38} status={it.get('status', '(未标注)')}")
            return
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 拉取 /v1/models 失败（不影响后续探测）：{e}")

    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else tokenhub_models_from_config()
    )
    if not models:
        print("没有要探测的模型。")
        return

    print(f"开始探测 {len(models)} 个模型（每档最多 3 次极短调用）…")
    results: list[ProbeResult] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for i, model in enumerate(models, 1):
            print(f"  [{i}/{len(models)}] {model} … ", end="", flush=True)
            r = await probe_model(client, base_url + "/chat/completions", key, model, args.delay)
            results.append(r)
            print(r.state)
            if r.state != "quota":
                await asyncio.sleep(args.delay)

    print_table(results)
    print_quirks(results)
    print_summary(results, online)


if __name__ == "__main__":
    asyncio.run(main())
