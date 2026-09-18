"""LLM 阶梯链状态 —— 只读配置与进程内健康态，**不发起任何推理调用**。

设计前提：TokenHub 免费额度有限且不刷新，所以诊断**绝不能靠探活**（探活就是烧额度）。
这里唯一的网络请求是启动时拉一次 `GET /v1/models` 拿「哪些档已停服 / 即将下线」，
它不消耗推理额度。

用法：
    uv run python scripts/llm_status.py                        # 全部场景
    uv run python scripts/llm_status.py --scene turtle_soup_judge
    uv run python scripts/llm_status.py --json                 # 机器可读，便于定时采集
"""

from __future__ import annotations

import argparse
import io
import json
import sys
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

from core import llm  # noqa: E402

#: 冷却中的档用这些 kind 名显示（与 core.llm 的分类一致）
_KIND_LABEL = {
    llm.KIND_RATE_LIMITED: "限流冷却",
    llm.KIND_QUOTA: "额度耗尽",
    llm.KIND_AUTH: "鉴权失败",
    llm.KIND_TRANSIENT: "抖动冷却",
    llm.KIND_FATAL: "参数错误",
    llm.KIND_UNAVAILABLE: "已停服",
}


def _collect() -> dict[str, Any]:
    """把配置与健康态拼成一份快照。**不产生任何推理调用。**"""
    llm.init()  # 会拉 /v1/models（不耗推理额度）+ 读 config/llm.yaml

    chains = llm.scene_chains()
    health = {h["slot"]: h for h in llm.health_snapshot()}
    providers = llm.providers_snapshot()

    scenes: dict[str, Any] = {}
    for name, slots in chains.items():
        scenes[name] = [
            {
                "order": i + 1,
                "slot": slot,
                **{
                    k: health.get(slot, {}).get(k)
                    for k in ("status", "cool_remaining_s", "exhaust_count", "imminent_offline")
                },
            }
            for i, slot in enumerate(slots)
        ]

    all_slots = sorted(health)
    return {
        "providers": providers,
        "scenes": scenes,
        "slots": [health[s] for s in all_slots],
        "totals": {
            "slots": len(all_slots),
            "ok": sum(1 for h in health.values() if h["status"] == "ok"),
            "cooling": sum(1 for h in health.values() if h["cool_remaining_s"]),
            "offline": sum(1 for h in health.values() if h["status"] == "offline"),
            "imminent_offline": sum(1 for h in health.values() if h.get("imminent_offline")),
            "exhausted": sum(1 for h in health.values() if h.get("exhaust_count")),
        },
    }


def _fmt_status(h: dict[str, Any]) -> str:
    status = h.get("status") or "?"
    if h.get("cool_remaining_s"):
        label = _KIND_LABEL.get(status, status)
        return f"{label} 剩余 {h['cool_remaining_s']}s"
    if status == "offline":
        return "已停服"
    return "ok"


def _print_human(data: dict[str, Any], only_scene: str | None) -> None:
    print()
    print("=" * 92)
    print("LLM 阶梯链状态（只读；未发起任何推理调用）")
    print("=" * 92)

    print("\nproviders")
    for name, p in data["providers"].items():
        mark = "✓ 已配置" if p["configured"] else "✗ 缺 api_key（该 provider 的档会被跳过）"
        print(f"  {name:<10} {mark:<40} {p['base_url']}")

    scenes = data["scenes"]
    if only_scene:
        scenes = {k: v for k, v in scenes.items() if k == only_scene}
        if not scenes:
            print(f"\n⚠️ 没有名为 '{only_scene}' 的 scene")
            return

    for name, slots in scenes.items():
        print(f"\n{name}  ({len(slots)} 档)")
        for s in slots:
            flags = []
            if s.get("imminent_offline"):
                flags.append("即将下线·优先烧")
            if s.get("exhaust_count"):
                flags.append(f"累计耗尽 {s['exhaust_count']} 次")
            suffix = ("  ← " + "，".join(flags)) if flags else ""
            print(f"  {s['order']:>2}. {s['slot']:<40} {_fmt_status(s)}{suffix}")

    t = data["totals"]
    print("\n" + "-" * 92)
    print(
        f"去重后共 {t['slots']} 档：可用 {t['ok']}，冷却中 {t['cooling']}，"
        f"已停服 {t['offline']}；其中 {t['imminent_offline']} 档已公告下线（仍可用，应优先烧）"
    )
    if t["exhausted"]:
        print(f"⚠️ 有 {t['exhausted']} 档出现过额度耗尽 —— 这些额度不会恢复，链会自动跳过")
    if not any(p["configured"] for n, p in data["providers"].items() if n == "zhipu"):
        print("⚠️ zhipu 没配 key → 链尾兜底不可用，TokenHub 全挂时调用会直接失败")


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM 阶梯链状态（零额度消耗）")
    parser.add_argument("--scene", help="只看指定 scene")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    data = _collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_human(data, args.scene)


if __name__ == "__main__":
    main()
