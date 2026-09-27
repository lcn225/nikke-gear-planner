"""
Streamlit GUI 后端适配层
将上游名册（input/cn_collect.json）+ 推荐表转换为 Character，调用竞价引擎，格式化输出
"""

import json
from typing import Dict, List, Tuple

import pandas as pd

from engine.bidding_engine import (
    BidEntry,
    CharacterRow,
    GlobalBiddingEngine,
    build_character_detail,
    build_character_ladder,
    character_rows_to_records,
)
from engine.roster_loader import RosterParseResult, load_roster, parse_roster
from models.character import Character
from models.targets import PARSED_PATH, load_targets


def load_roster_from_json_content(content: bytes, mode: str = "PVE") -> RosterParseResult:
    """
    从 GUI 上传的 JSON 文件内容加载阵容（上游名册格式，见 input/数据说明.md）。

    目标词条从 data/targets_parsed.json 现取 —— 上传的文件只含**账号现状**，
    养成目标是全服通用的攻略知识，不随账号走，两者的变化频率也不同。
    """
    data = json.loads(content.decode("utf-8"))
    result = parse_roster(data, load_targets(PARSED_PATH, mode=mode))
    result.mode = mode
    return result


def run_calculation(
    characters: List[Character],
    stones: int,
    credits: int
) -> Tuple[List[BidEntry], Dict[str, List[str]]]:
    """
    运行全局竞价计算

    Returns:
        (按排序分降序的 BidEntry 列表, 角色名 → 未达成的 primary 目标)
        后者要给角色榜用（标注哪些角色还没铺开核心词条），所以一起返回。
    """
    engine = GlobalBiddingEngine(stones_held=stones, credits_held=credits)
    return engine.run(characters), engine.unmet_primary


def build_character_dataframe(
    characters: List[Character],
    bids: List[BidEntry],
    unmet_primary: Dict[str, List[str]],
    unavailable: Dict[str, str] = None,
    top_n: int = 0,
) -> pd.DataFrame:
    """
    角色培养榜的 DataFrame：一行 = 一个角色的下一步。

    这是主视图（等价于 CLI 的角色培养榜）。明细天梯仍可用
    format_bids_to_dataframe 拿。
    """
    rows = build_character_ladder(
        characters, bids, unmet_primary, unavailable=unavailable or {})
    if not rows:
        return pd.DataFrame()
    if top_n:
        rows = rows[:top_n]

    # 单元格文案由 character_rows_to_records 统一生成（纯函数、可单独测），
    # 这里只负责套一层 DataFrame —— 免得 CLI 与 GUI 的文案各写一遍后走偏。
    return pd.DataFrame(character_rows_to_records(rows))


def format_bids_to_dataframe(
    bids: List[BidEntry],
    stones_held: int,
    top_n: int = 20
) -> pd.DataFrame:
    """
    将 BidEntry 列表格式化为 Pandas DataFrame。

    top_n <= 0 表示**全部**（与 generate_unified_ladder_report 的口径一致）。
    早期写成 `bids[:top_n]`，top_n=0 会静默返回空表。
    """
    if not bids:
        return pd.DataFrame()

    op_icons = {
        "升级": "🟢",
        "开光": "🆕",
        "洗词条": "🟡",
        "洗数值": "🟠",
        "洗词条+洗数值": "🟣",
    }

    display_bids = bids[:top_n] if top_n > 0 else bids
    rows = []
    for bid in display_bids:
        target_str = "+".join(sorted(bid.target_set)) if bid.target_set else "-"
        op_display = f"{op_icons.get(bid.action_type, '🔵')} {bid.action_type}"
        
        # 库存警告判断
        warning = ""
        if bid.equivalent_cost > stones_held:
            warning = "🔴 库存不足"
        elif bid.equivalent_cost > stones_held * 0.8:
            warning = "⚠️ 逼近红线"
        else:
            warning = "—"
        
        rows.append({
            "顺位": bid.priority,
            "角色": bid.character_name,
            # 档位权重：顺位 = ROI × 档位 × 库存折减。写出来才能自查
            # 「为什么这条 ROI 更高却排在后面」。
            "档位": f"×{bid.tier_weight:.2f}" if bid.tier else "—",
            "部位": bid.gear_slot,
            "操作": op_display,
            "目标组合": target_str,
            "等效成本(石)": round(bid.equivalent_cost, 2),
            "预期增幅": f"{bid.expected_damage_gain*100:.2f}%",
            "ROI": round(bid.roi, 4),
            "主目标未达成": "⏸" if bid.gated else "",
            "警告": warning,
            "详情": bid.action_detail,
        })
    
    return pd.DataFrame(rows)


def get_bid_statistics(bids: List[BidEntry]) -> dict:
    """获取竞价统计信息"""
    if not bids:
        return {"total": 0, "types": {}}
    
    type_counts = {}
    for b in bids:
        type_counts[b.action_type] = type_counts.get(b.action_type, 0) + 1
    
    return {
        "total": len(bids),
        "types": type_counts,
        "top_roi": bids[0].roi if bids else 0,
    }