"""
历史记录管理模块
负责保存和加载计算结果历史

一条记录 = **一次计算的可回放快照**。角色培养榜是 f(名册, 竞价, 门禁) 的函数，
所以要能独立回放，记录里必须三样都齐：

    bids           竞价明细（一直是主体，约 900KB）
    roster         名册装备快照（Character.to_dict，约 96KB）
    targets        该模式下这批角色的目标切片（models.targets.snapshot_targets，约 79KB）
    unmet_primary  primary 门禁结果（很小）

**为什么目标也要存**：目标取自 data/targets_parsed.json（随仓库分发的快照），
只存名册、目标现取的话，目标表一更新，重建出来的就是「旧名册 × 新目标」——
看着正常、实际混源，正是 R1a 修掉的那类毛病换了个入口进来。
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from models.character import Character
from models.targets import load_targets_from_snapshot

HISTORY_DIR = "data/history"


def ensure_history_dir():
    """确保历史记录目录存在"""
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)


def save_history(
    bids: List,
    stones: int,
    credits: int,
    character_count: int,
    mode: str = "",
    roster: Optional[List] = None,
    targets: Optional[dict] = None,
    unmet_primary: Optional[dict] = None,
) -> str:
    """
    保存本次计算结果到历史记录

    Args:
        bids: BidEntry 对象列表
        stones: 石头库存
        credits: 信用点库存
        character_count: 角色数量
        mode: 本跑用的养成目标模式（PVE/PVP）。读回时要靠它确定用哪份目标，
            所以有快照就必须有它 —— 没有模式的目标切片是无从解释的。
        roster: Character 对象列表（本模块按 to_dict() 落盘）
        targets: models.targets.snapshot_targets() 的产物（原始切片）
        unmet_primary: 引擎的 primary 门禁结果 {角色名: [未达成描述]}

    后四项一起构成「可回放的快照」。**默认全空** —— 那样存出来的仍是旧格式
    （只有竞价明细），读回时角色榜重建不出来，见 read_snapshot。
    没传就说明调用方没有名册（例如只跑竞价跑不出角色榜的场景），不是漏存。

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
        "mode": mode,
        # 名册快照。存 to_dict() 的产物而不是 Character 本身（后者不可 JSON 化），
        # targets 不在 to_dict 里 —— 它是全服通用的攻略知识，单独存一份切片，
        # 见模块开头。
        "roster": [c.to_dict() for c in (roster or [])],
        "targets": targets or {},
        "unmet_primary": unmet_primary or {},
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


@dataclass
class HistorySnapshot:
    """从历史记录重建出来的角色榜三输入（去掉竞价，那个本来就在记录里）。"""
    characters: List[Character]
    unmet_primary: Dict[str, List[str]]
    mode: str
    # 快照里没有目标的角色名。当次运行时它们同样拿不到目标（推荐表查无此人），
    # 所以这不是「读丢了」，但也不能不吭声 —— 它们不会出现在角色榜上。
    unmatched_targets: List[str] = field(default_factory=list)


def read_snapshot(data: dict) -> Optional[HistorySnapshot]:
    """
    从历史记录里重建 (名册, 门禁结果)。**旧记录没有快照，返回 None。**

    和保存侧同一个道理：名册与目标必须**同源**。快照缺哪一样都读不出来，
    宁可回落到「无法重建角色榜」的说明文字，也不拿当前的目标表去配旧名册 ——
    那会得到一张看着正常、实际混源的表（R1a 的根因）。

    抛错而不是降级：调用方（GUI）要知道是「这份记录本来就没有快照」还是
    「有快照但坏了」，前者该显示说明文字，后者该显示错误。
    """
    raw_roster = data.get("roster") or []
    if not raw_roster:
        return None       # 旧格式记录：本来就没打算回放角色榜

    mode = data.get("mode") or ""
    if not mode:
        raise ValueError(
            "历史记录带名册快照却没有 mode，无法确定它是哪份目标算出来的。"
        )
    raw_targets = data.get("targets") or {}
    if not raw_targets:
        # 少了目标切片，每个角色都会是 targets=None，从而被角色榜整批跳过 ——
        # 界面上会显示成「所有角色已毕业」，一句假话。这里直接拦住。
        raise ValueError(
            "历史记录带名册快照却没有目标切片（targets），重建角色榜会得到"
            "空名册效果（显示成「所有角色已毕业」）。这条记录已损坏，"
            "请重新运行计算生成新记录。"
        )

    characters = [Character.from_dict(d) for d in raw_roster]
    by_name = load_targets_from_snapshot(raw_targets, mode)
    unmatched = []
    for char in characters:
        char.targets = by_name.get(char.name)
        if char.targets is None:
            unmatched.append(char.name)

    return HistorySnapshot(
        characters=characters,
        unmet_primary=data.get("unmet_primary") or {},
        mode=mode,
        unmatched_targets=unmatched,
    )


# resolve_replay 的四种来源
KIND_SNAPSHOT = "snapshot"   # 记录自带快照，自包含
KIND_BROKEN = "broken"       # 有快照但读不出来（记录损坏）
KIND_BORROWED = "borrowed"   # 旧记录 + 与上一轮同源，借用会话里的名册
KIND_NONE = "none"           # 旧记录且非同源，重建不出来


@dataclass
class ReplayResult:
    """加载一条历史时，角色培养榜那三个输入从哪来。"""
    characters: Optional[List[Character]] = None
    unmet_primary: Optional[Dict[str, List[str]]] = None
    kind: str = KIND_NONE
    mode: str = ""
    unmatched_targets: List[str] = field(default_factory=list)
    error: str = ""          # kind == KIND_BROKEN 时的原因


def resolve_replay(
    data: dict,
    history_path: Optional[str] = None,
    last_run_path: Optional[str] = None,
    last_run_characters: Optional[List[Character]] = None,
    last_run_unmet_primary: Optional[Dict[str, List[str]]] = None,
) -> ReplayResult:
    """
    决定「加载这条历史时，角色榜拿哪份名册与门禁」。

    角色榜是 f(名册, 竞价, 门禁) 的函数，三者必须同源 —— 这是 R1a 的教训：
    拿旧名册配新竞价，会渲染出一张看着正常、实际错配的表。四种来源：

    1. **记录自带快照** → 自包含，冷启动直接加载也能重建（R1b）
    2. 有快照但读坏了 → 报错，不凑合（宁可没有，也不要一张错的榜）
    3. **旧记录**（R1b 之前存的，只有竞价明细）→ 名册只能「借」：
       仅当这份历史就是上一轮计算自己存出去的那个文件（路径相同）才允许。
       那是可证明的同源，不是猜 —— 这条路径的常见形态是「刚跑完计算，
       点侧边栏刚存下的那条」，那时名册与竞价本就是同一次的产物。
    4. 旧记录且非同源 → 什么都没有，回落到说明文字

    纯函数，不碰 Streamlit：这一段决策原先写在 app.py 里，WSL 侧
    import 不了 streamlit 就一行都测不了，只能靠复刻逻辑做真值表。
    """
    if data.get("roster"):
        try:
            snap = read_snapshot(data)
        except Exception as e:
            return ReplayResult(kind=KIND_BROKEN, error=str(e))
        return ReplayResult(
            characters=snap.characters,
            unmet_primary=snap.unmet_primary,
            kind=KIND_SNAPSHOT,
            mode=snap.mode,
            unmatched_targets=snap.unmatched_targets,
        )

    # 旧记录。两个路径都必须非空才比 —— 否则冷启动时 None == None 会退化命中，
    # 把「没有名册」当成「名册是对的」。
    if history_path and last_run_path and history_path == last_run_path:
        return ReplayResult(
            characters=last_run_characters,
            unmet_primary=last_run_unmet_primary,
            kind=KIND_BORROWED,
        )

    return ReplayResult(kind=KIND_NONE)


def list_history(limit: int = 20) -> List[dict]:
    """
    列出所有历史记录（按时间倒序）

    Returns:
        每条记录包含: {filepath, filename, timestamp, stones, credits,
                      total_bids, character_count, mode, has_snapshot, size}
        `size` 是文件字节数 —— 每份记录约 1.1MB（竞价明细 ~900KB +
        名册与目标快照 ~175KB），界面上要让人看得见体积在长。
        `has_snapshot` 为假的是 R1b 之前存的旧记录：能看明细天梯，
        重建不出角色培养榜。
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
                    "mode": data.get("mode", ""),
                    "has_snapshot": bool(data.get("roster")),
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
