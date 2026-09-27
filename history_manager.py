"""
历史记录管理模块
负责保存和加载计算结果历史
"""

import json
import os
from datetime import datetime
from typing import List, Optional

HISTORY_DIR = "data/history"


def ensure_history_dir():
    """确保历史记录目录存在"""
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)


def save_history(
    bids: List,
    stones: int,
    credits: int,
    character_count: int
) -> str:
    """
    保存本次计算结果到历史记录

    Args:
        bids: BidEntry 对象列表
        stones: 石头库存
        credits: 信用点库存
        character_count: 角色数量

    Returns:
        保存的文件路径
    """
    ensure_history_dir()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}.json"
    filepath = os.path.join(HISTORY_DIR, filename)

    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stones": stones,
        "credits": credits,
        "character_count": character_count,
        "total_bids": len(bids),
        "bids": [
            {
                "priority": b.priority,
                "character_name": b.character_name,
                "gear_slot": b.gear_slot,
                "action_type": b.action_type,
                "target_set": list(b.target_set) if b.target_set else [],
                "equivalent_cost": b.equivalent_cost,
                "expected_damage_gain": b.expected_damage_gain,
                "roi": b.roi,
                "action_detail": b.action_detail,
                "resource_desc": b.resource_desc,
                # 门禁与档位折算的结果。漏存不会报错，只会让读回的历史
                # 丢掉 ⏸ 标记和档位列 —— 看起来像「这条本来就该排这儿」。
                "gated": b.gated,
                "tier": b.tier,
                "tier_weight": b.tier_weight,
                "sort_score": b.sort_score,
            }
            for b in bids
        ]
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filepath


def load_history(filepath: str) -> dict:
    """加载单条历史记录"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def list_history(limit: int = 20) -> List[dict]:
    """
    列出所有历史记录（按时间倒序）

    Returns:
        每条记录包含: {filepath, filename, timestamp, stones, credits,
                      total_bids, character_count, size}
        `size` 是文件字节数 —— 每份记录约 900KB，界面上要让人看得见体积在长。
    """
    ensure_history_dir()

    files = []
    for f in os.listdir(HISTORY_DIR):
        if f.endswith(".json"):
            filepath = os.path.join(HISTORY_DIR, f)
            try:
                with open(filepath, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                files.append({
                    "filepath": filepath,
                    "filename": f,
                    "timestamp": data.get("timestamp", "未知"),
                    "stones": data.get("stones", 0),
                    "credits": data.get("credits", 0),
                    "total_bids": data.get("total_bids", 0),
                    "character_count": data.get("character_count", 0),
                    "size": os.path.getsize(filepath),
                })
            except Exception:
                continue

    # 按文件名（时间戳）倒序排列
    files.sort(key=lambda x: x["filename"], reverse=True)
    return files[:limit]


def delete_history(filepath: str) -> bool:
    """
    删除单条历史记录。返回是否真的删掉了。

    只删 data/history/ 底下的 .json —— 传进来的路径若指向别处就拒绝，
    免得 GUI 里一个字符串拼错就把别的文件删了。
    """
    target = os.path.abspath(filepath)
    root = os.path.abspath(HISTORY_DIR)
    if not target.startswith(root + os.sep) or not target.endswith(".json"):
        return False
    if os.path.exists(target):
        os.remove(target)
        return True
    return False
