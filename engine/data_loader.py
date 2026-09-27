# engine/data_loader.py

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional, Dict, List, Set

from config import TIER_VALUE_MATRIX
from models.targets import CharTargets, TargetSpec

# ────────────────────────────────────────────────────────────
# 本地配置文件路径
# ────────────────────────────────────────────────────────────

PHYSICAL_CONFIG_PATH = "data/character_physical_config.json"


# ────────────────────────────────────────────────────────────
# 数据结构
# ────────────────────────────────────────────────────────────

@dataclass
class CharacterPhysicalData:
    name: str
    base_ammo: int
    fire_rate: float
    reload_time: float
    is_attacker: bool
    cs_threshold: Optional[float]
    anti_ammo: bool
    # 全部目标词条（primary ∪ secondary）的标准名。引擎的集合语义用这个。
    targets: List[str] = field(default_factory=list)
    # 主副分层与毕业面板，见 models/targets.py。引擎靠 primary/secondary 决定
    # 候选队列的开放顺序，panel 只做展示。
    primary: List[TargetSpec] = field(default_factory=list)
    secondary: List[TargetSpec] = field(default_factory=list)
    panel: Dict[str, float] = field(default_factory=dict)
    # 蓄力武器的两个量，生成快照时从上游角色档案推导（口径见 config.py 的常量）：
    #   charge_time —— 普攻描述里的「蓄力时间」秒数
    #   base_time   —— charge_time ×(1 − 技能蓄速) + 0.35（硬直动画）
    # 非蓄力武器均为 None，此时蓄速乘区恒为 1.0。
    charge_time: Optional[float] = None
    base_time: Optional[float] = None


# ────────────────────────────────────────────────────────────
# 目标词条
# ────────────────────────────────────────────────────────────

def targets_from_char(targets: Optional[CharTargets]) -> dict:
    """
    把角色的养成目标摊平成 CharacterPhysicalData 需要的几个字段。

    目标词条**已经是标准名**（翻译只发生在 buff_aliases.py 那一层），
    这里再校验一次：非标准名直接抛错。旧实现在引擎里就地改名，一旦改错方向
    （曾把「最大装弹数」改回「最大装弹量」）就查表静默返回 0.0，装弹收益算成零。
    """
    if targets is None:
        return {"targets": [], "primary": [], "secondary": [], "panel": {}}

    all_buffs = targets.all_buffs()
    unknown = sorted(b for b in all_buffs if b not in TIER_VALUE_MATRIX)
    if unknown:
        raise KeyError(
            f"目标词条含非标准名 {unknown}（角色 {targets.mode} 模式）。"
            f"标准名见 config.BUFF_NAMES；外部写法应在 buff_aliases.py 翻译。"
        )
    return {
        "targets": all_buffs,
        "primary": targets.primary,
        "secondary": targets.secondary,
        "panel": dict(targets.panel),
    }


# ────────────────────────────────────────────────────────────
# 本地物理数据加载
# ────────────────────────────────────────────────────────────

_local_physical_cache: Dict[str, dict] = {}

def load_local_physical_config() -> Dict[str, dict]:
    """加载本地物理配置文件"""
    global _local_physical_cache
    if _local_physical_cache:
        return _local_physical_cache
    
    path = Path(PHYSICAL_CONFIG_PATH)
    if not path.exists():
        print(f"⚠️ 本地物理配置文件不存在: {PHYSICAL_CONFIG_PATH}")
        return {}
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 文件顶层是 {_meta, characters}（随仓库分发的静态快照）。
    # 拿不到 characters 说明文件不是本项目的产物或已损坏，直接报错而不是静默当成空。
    if "characters" not in data:
        raise ValueError(
            f"{PHYSICAL_CONFIG_PATH} 结构不对：顶层应有 characters 键。"
            f"请恢复仓库中该文件的原始副本。"
        )
    _local_physical_cache = data["characters"]
    return _local_physical_cache


# ────────────────────────────────────────────────────────────
# 核心加载函数（只读本地静态快照，不访问网络）
# ────────────────────────────────────────────────────────────

# 缓存**只存物理部分**（targets 恒为空）。目标词条是每次调用现场贴上去的：
# 同一角色的不同模式（PVE/PVP）目标不同，把 targets 存进缓存再 replace 出去，
# 迟早会出现「先跑 PVE 再跑 PVP，拿到 PVE 目标」这种跨调用污染。
_physical_data_cache: Dict[str, CharacterPhysicalData] = {}


def get_character_physical_data(
    name: str,
    targets: Optional[CharTargets] = None,
) -> Optional[CharacterPhysicalData]:
    """
    获取角色物理数据 + 贴上养成目标。优先从本地配置文件读取，若缺失则尝试 API。
    """
    base = _physical_data_cache.get(name)
    if base is None:
        base = _load_physical(name)
        if base is None:
            return None
        _physical_data_cache[name] = base

    # 复制而不是原地改：缓存对象是跨调用共享的。
    return replace(base, **targets_from_char(targets))


# 已经报过警的角色名。入口通常先调 physical_readiness() 出一份跳过清单，
# 引擎再跑时会遇到同一批角色 —— 不去重就会把同一句话打印两遍。
_warned: set = set()


def _warn_once(name: str, reason: str) -> None:
    if name in _warned:
        return
    _warned.add(name)
    print(f"⚠️ 跳过 {name}：{reason}")


def _load_physical(name: str) -> Optional[CharacterPhysicalData]:
    """只读物理字段，targets 留空。缺必需字段时返回 None（跳过该角色）。"""
    local_config = load_local_physical_config()
    if name in local_config:
        raw = local_config[name]
        reason = _missing_reason(raw)
        if reason:
            # 不拿 0 兜底：fire_rate=0 会让装弹乘区除零或算出无穷大，
            # 静默换成一个假数字则更糟 —— 那等于把「不知道」伪装成「知道」。
            _warn_once(name, reason)
            return None
        return CharacterPhysicalData(
            name=name,
            base_ammo=raw["base_ammo"],
            fire_rate=raw["fire_rate"],
            reload_time=raw["reload_time"],
            is_attacker=raw.get("is_attacker", True),
            cs_threshold=raw.get("cs_threshold"),
            anti_ammo=raw.get("anti_ammo", False),
            # 蓄力武器专有。非蓄力角色这两个是 None，蓄速乘区恒为 1.0 ——
            # 漏了它们不会报错，只会让所有蓄力角色的蓄速收益静默算错。
            charge_time=raw.get("charge_time"),
            base_time=raw.get("base_time"),
        )

    # 静态快照里没有这个角色。引擎只读随仓库分发的那一份，不联网兜底。
    _warn_once(name, f"不在 {PHYSICAL_CONFIG_PATH} 中"
                     f"（该文件是静态快照，缺角色时无法计算）")
    return None


# 乘区计算必需的字段。缺任何一个就算不出伤害，只能跳过。
REQUIRED_PHYSICAL_FIELDS = ("base_ammo", "fire_rate", "reload_time")


def _missing_reason(raw: dict) -> Optional[str]:
    """
    物理参数是否足以计算乘区；不足时返回原因，可算返回 None。

    ⚠️ 这里**判不出**「单格缺失」还是「整块缺失」—— 本地快照里没有足够信息。
    已实测：QUEEN（真）与 雪子 的「详细面板资讯」是**整块空的**（最佳攻击范围/
    暴击率/暴击伤害/武器伤害/爆裂持续时间/射速基准六项全无），不是只缺射速一格；
    角色存在，只是上游编辑者还没填那块面板。

    所以措辞不能写成「上游该格为空」——那会让人以为单格缺失、另有办法，
    进而去翻别的数据源，而实际上除了等上游补齐没有任何事可做。精确到块的判定
    要看整理前的原始行结构，那部分不在仓库内。
    """
    missing = [f for f in REQUIRED_PHYSICAL_FIELDS if raw.get(f) is None]
    if not missing:
        return None
    raw_hint = "、".join(
        f"{f}={raw.get(f + '_raw')!r}" for f in missing if raw.get(f + "_raw")
    )
    # 不写「某格为空」也不写死角色名：本地快照判不出整块还是单格。
    return (f"物理参数缺 {missing}（上游没有给出{': ' + raw_hint if raw_hint else ''}），"
            f"无法计算乘区。{PHYSICAL_CONFIG_PATH} 是静态快照，"
            f"缺的字段只能等上游补齐后在外部更新该文件，期间没有别的办法。")


def physical_skip_label(name: str) -> str:
    """
    给报表表格用的**短**标签，完整原因见 physical_readiness。

    表格里塞整句「物理参数缺 ['fire_rate']（上游为空），无法计算乘区。数据文件是
    静态快照，缺的字段只能等上游补齐。」会把 markdown 表格撑坏，而且那句话入口
    已经单独打印过了。这里只要说清楚「它是被跳过的，不是没事可做」。
    """
    reason = physical_readiness(name)
    if not reason:
        return ""
    return "无物理数据" if "不在" in reason else "物理参数不全"


def physical_readiness(name: str) -> Optional[str]:
    """
    该角色能否参与计算；不能则返回原因，能则 None。

    给入口做「参与计算 / 被跳过」清单用 —— 只有「在不在配置文件里」不够，
    还要看必需字段是否齐全，否则清单会漏掉雪子/QUEEN（真）这种半残条目。
    """
    cfg = load_local_physical_config()
    if name not in cfg:
        reason = f"不在 {PHYSICAL_CONFIG_PATH} 中（静态快照缺该角色）"
    else:
        reason = _missing_reason(cfg[name])
    if reason:
        _warned.add(name)      # 入口已经报过，引擎再遇到就不要再喊一遍
    return reason