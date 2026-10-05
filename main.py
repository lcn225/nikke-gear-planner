#!/usr/bin/env python3
"""
NIKKE 装备优化规划器 — 全局竞价大排队系统 主入口

基于 BASE_DATA_SPECIFICATION（T10装备全局ROI算法DeepResearch）：
- 五大乘区相对提升率收益函数
- 无放回超几何选择 + 几何分布期望
- 2+3 累加锁词门票
- 6.67/18.93/34.79 渐进式洗数值期望
- 1.5M 影子汇率换算
- 单一全局降序混合竞价天梯

数据源（三者分工，别再混）：
    账号现状   input/cn_collect.json          我装备了什么，每次玩都变  ← 本入口读这个
    角色策略   data/targets_parsed.json       这个角色该怎么养（随仓库分发的快照）
    角色物理   data/character_physical_config.json                    ← engine/data_loader.py

主输出是**角色培养榜**：一行 = 一个角色的下一步，排序「档位优先，档内按 ROI」。
    为什么不把上千条明细平铺：用户的问题是「我现在该把资源用到哪」，答案是
    **某个角色的某件事**；平铺还会让档位靠前的角色被自己的几十条候选刷屏，
    把别的角色挤出视野。明细天梯仍在，加 `--detail` 看。

    ⚠️ 档位是**次序**不是**倍率**。按 ROI×权重 一把梭会让 T2/T3 的便宜动作
    插到 T0 前面（实测 T3 的尼恩：蓝色海洋能排到第 9），而 T0 是永久保质期
    角色，投进去的每分资源都有回报。倍率只用于同一档位内部比较。

用法：
    python3 main.py                      # 读 input/cn_collect.json，交互输入资源
    python3 main.py --stones 100 --credits 5000000  # 指定资源
    python3 main.py --detail --top 20    # 附上明细竞价天梯（前 20 条）
    python3 main.py --mode PVP           # 换模式（默认 PVE）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SHADOW_PRICE_LAMBDA, TIER_WEIGHT_Q, tier_weight
from console_io import install_console_fallback
from engine.bidding_engine import (
    GlobalBiddingEngine,
    build_character_ladder,
    generate_character_ladder_report,
    generate_unified_ladder_report,
)
from engine.data_loader import physical_readiness, physical_skip_label
from engine.roster_loader import ROSTER_PATH, load_roster_with_targets
from models.targets import PARSED_PATH

BANNER = """
╔══════════════════════════════════════════════════════╗
║     NIKKE 装备强化与洗练 ROI 智能规划系统            ║
║     后期长草期资源分配最优决策工具                    ║
╚══════════════════════════════════════════════════════╝
"""


def _parse_args(args: list[str]) -> dict:
    opts = {"input": None, "targets": None, "mode": "PVE",
            "stones": None, "credits": None, "top": 0, "detail": False}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--detail":
            opts["detail"] = True
        elif arg in ("--input", "--targets", "--mode", "--stones", "--credits", "--top") \
                and i + 1 < len(args):
            i += 1
            key = arg[2:]
            opts[key] = args[i] if key in ("input", "targets", "mode") else int(args[i])
        else:
            print(f"  忽略未知参数: {arg}")
        i += 1
    return opts


def _prompt_inventory(stones: int | None, credits: int | None) -> tuple[int, int]:
    """交互式输入资源库存。上游名册只有装备现状，不含库存，必须问。"""
    try:
        if stones is None:
            raw = input("  请输入持有石头数 [默认 100]: ").strip()
            stones = int(raw) if raw else 100
        if credits is None:
            raw = input("  请输入持有信用点数 [默认 5000000]: ").strip()
            credits = int(raw) if raw else 5_000_000
    except (EOFError, KeyboardInterrupt):
        print()
        stones = 100 if stones is None else stones
        credits = 5_000_000 if credits is None else credits
    return stones, credits


def main():
    # 最先装：下面每一段输出都带 emoji，重定向/管道下编码是 GBK，
    # 没有这层降级时 `print("❌ 加载失败")` 自己就会抛 UnicodeEncodeError。
    install_console_fallback()

    opts = _parse_args(sys.argv[1:])
    print(BANNER)

    # ── 加载上游名册 + 养成目标 ──
    roster_path = opts["input"] or ROSTER_PATH
    targets_path = opts["targets"] or PARSED_PATH
    print(f"  从名册加载: {roster_path}")
    print(f"  从推荐表加载: {targets_path}（模式 {opts['mode']}）")
    try:
        result = load_roster_with_targets(roster_path, targets_path, mode=opts["mode"])
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"\n  ❌ 加载失败: {e}\n")
        return 1
    characters = result.characters

    print(result.format_report())

    if not characters:
        print("\n  没有角色数据，退出。")
        return 1

    # ── 物理参数覆盖情况 ──
    # 不能只看「在不在配置文件里」：雪子/QUEEN（真）在文件里但射速那格是空的，
    # 引擎会跳过它们。用 physical_readiness 才数得准。
    reasons = {c.name: physical_readiness(c.name) for c in characters}
    bad = {n: r for n, r in reasons.items() if r}
    print(f"  物理参数: {len(characters) - len(bad)}/{len(characters)} 个角色可算")
    for name, reason in bad.items():
        print(f"  ⚠️ 跳过 {name}：{reason}")

    # ── 资源库存 ──
    print()
    stones, credits = _prompt_inventory(opts["stones"], opts["credits"])

    # ── 运行全局竞价引擎 ──
    print(f"\n{'=' * 60}")
    print(f"  正在运行全局竞价大排队计算...")
    print(f"  五大乘区模型: (ATK)×(ELE)×(Ammo)×(CS)×(Crit)")
    print(f"  影子汇率: 1 石头 = {SHADOW_PRICE_LAMBDA / 1e4:.0f}万 信用点")
    print(f"  跨角色折算: 档位权重 q={TIER_WEIGHT_Q}"
          f"（T0 ×{tier_weight('0'):.2f} / T1 ×{tier_weight('1'):.2f} / "
          f"T3 ×{tier_weight('3'):.2f} / 仓管 ×{tier_weight('cg'):.2f}）")

    engine = GlobalBiddingEngine(stones_held=stones, credits_held=credits)
    bids = engine.run(characters)

    # ── 输出 ──
    print(f"\n  资源库存: {stones} 石头 | {credits:,} 信用点")
    print(f"  全局共 {len(bids)} 条竞价动作")
    type_counts: dict[str, int] = {}
    for b in bids:
        type_counts[b.action_type] = type_counts.get(b.action_type, 0) + 1
    for t, c in type_counts.items():
        print(f"    {t}: {c} 条")

    gated_n = sum(1 for b in bids if b.gated)
    if gated_n:
        print(f"  ⏸ 被主目标门禁拦住 {gated_n} 条（仍列出，标了 ⏸）")

    # 参与计算的角色清单（验证用：与上面的跳过清单相加应等于角色总数）
    participating = sorted({b.character_name for b in bids})
    skipped_by_engine = sorted(set(c.name for c in characters) - set(participating))
    print(f"  参与计算 {len(participating)} 个角色 | 无产出 {len(skipped_by_engine)} 个")
    if skipped_by_engine:
        print(f"    无产出: {', '.join(skipped_by_engine)}")

    print(f"\n{'=' * 60}\n")

    # ── 主视图：角色培养榜 ──
    # 一行 = 一个角色的下一步。用户的问题是「我该把资源用到哪」，
    # 答案是某个角色的某件事，不是「第 303 顺位那条洗练」。
    # 表格里只用短标签；完整原因上面已经逐条打印过
    unavailable = {n: physical_skip_label(n) for n in bad}
    rows = build_character_ladder(
        characters, bids, engine.unmet_primary, unavailable=unavailable,
    )
    print(generate_character_ladder_report(rows, stones, credits))

    # ── 明细天梯（可选）──
    if opts["detail"]:
        print()
        print(generate_unified_ladder_report(
            bids, stones_held=stones, credits_held=credits, top_n=opts["top"],
            characters=characters, unmet_primary=engine.unmet_primary,
        ))

    # ── 快速执行建议 ──
    if bids:
        print(f"\n  💡 竞价公式: ROI = ΔB / ΔC  (ΔB=相对伤害增幅, ΔC=等效石头成本)")
        print(f"  💡 五大乘区: (ATK=2.0+攻%)×(ELE=1.1+优%)×(Ammo占空比)×(CS秒蓄门槛)×(Crit极弱)")
        print(f"  💡 影子汇率: 1 石头 = {SHADOW_PRICE_LAMBDA / 1e4:.0f}万 信用点")
        print(f"  💡 洗数值期望: 1条=6.67石 / 2条=18.93石 / 3条=34.79石")
        print(f"  💡 无放回超几何选择 + 2+3累加锁词门票")
        print(f"  💡 建议从第 1 顺位开始，依次向下执行\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
