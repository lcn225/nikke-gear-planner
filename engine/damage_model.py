"""
五大乘区伤害模型 — 累乘相对提升率收益函数

数据来源：从 data_loader 获取角色物理配置（本地 JSON + 可选 API）
"""

from dataclasses import dataclass, field
from typing import Optional
from engine.data_loader import get_character_physical_data
from models.targets import CharTargets, TargetSpec
from config import (
    D_BUFF,
    BASE_ELE_MULTIPLIER,
    BASE_CHAR_ATK,
    HARD_ANIM_SEC,
    TIER_VALUE_MATRIX,
)


@dataclass
class CharPhysicalProfile:
    """角色的物理战术配置（用于乘区计算）+ 养成目标"""
    name: str
    # 全部目标词条（primary ∪ secondary）。乘积区/洗练枚举的集合语义用这个。
    targets: list[str]
    base_ammo: int
    fire_rate: float
    reload_time: float
    anti_ammo: bool
    cs_threshold: Optional[float]
    is_attacker: bool
    # 主副分层：primary 未达成时引擎拦住纯 secondary 的候选。见 models/targets.py。
    primary: list[TargetSpec] = field(default_factory=list)
    secondary: list[TargetSpec] = field(default_factory=list)
    # 毕业面板（展示用，不参与判定）
    panel: dict[str, float] = field(default_factory=dict)
    # 蓄力武器专有，非蓄力为 None（见 engine/data_loader.py 的字段说明）
    charge_time: Optional[float] = None
    base_time: Optional[float] = None


def get_profile(
    char_name: str,
    targets: Optional[CharTargets] = None,
) -> Optional[CharPhysicalProfile]:
    """
    从 data_loader 获取角色物理配置，并贴上该角色的养成目标。

    Args:
        char_name: 角色名
        targets: 可选，models.targets.CharTargets（由 engine/roster_loader.py 注入）
    """
    data = get_character_physical_data(char_name, targets)
    if data is None:
        return None
    return CharPhysicalProfile(
        name=data.name,
        targets=data.targets,
        primary=data.primary,
        secondary=data.secondary,
        panel=data.panel,
        base_ammo=data.base_ammo,
        fire_rate=data.fire_rate,
        reload_time=data.reload_time,
        anti_ammo=data.anti_ammo,
        cs_threshold=data.cs_threshold,
        is_attacker=data.is_attacker,
        charge_time=data.charge_time,
        base_time=data.base_time,
    )


# ────────────────────────────────────────────────────────────
# 乘区 1：攻击力 M_ATK
# ────────────────────────────────────────────────────────────

def compute_m_atk(a_ol: float) -> float:
    return D_BUFF + a_ol


def compute_m_atk_upgrade(current_atk: float, atk_gain: float) -> float:
    if current_atk <= 0 or atk_gain <= 0:
        return 1.0
    return (current_atk + atk_gain) / current_atk


# ────────────────────────────────────────────────────────────
# 乘区 2：优越代码 M_ELE
# ────────────────────────────────────────────────────────────

def compute_m_ele(e_ol: float) -> float:
    return BASE_ELE_MULTIPLIER + e_ol


# ────────────────────────────────────────────────────────────
# 乘区 3：最大装弹数占空比 M_Ammo
# ────────────────────────────────────────────────────────────

def compute_m_ammo(ammo_ol: float, profile: CharPhysicalProfile) -> float:
    if profile.anti_ammo:
        return 1.0 / (1.0 + 10.0 * ammo_ol)
    c_eff = profile.base_ammo * (1.0 + ammo_ol)
    k_const = profile.fire_rate * profile.reload_time
    if c_eff + k_const <= 0:
        return 0.0
    return c_eff / (c_eff + k_const)


# ────────────────────────────────────────────────────────────
# 乘区 4：蓄力速度 M_CS（修复版）
# ────────────────────────────────────────────────────────────

def compute_m_cs(cs_ol: float, profile: CharPhysicalProfile) -> float:
    """
    蓄力速度乘区（原「修复版」，现改为按角色推导，不再硬编码基准时间）。

    单发时间 = 蓄力时间 ×(1 − 技能蓄速 − 过载蓄速) + 硬直动画
             = base_time − 蓄力时间 × min(cs_threshold, cs_ol)

    `base_time` 已经把「蓄力时间 ×(1 − 技能蓄速) + 硬直动画」折进去了，
    在生成快照时从上游角色档案推导好，写进物理快照（推导口径见 config.py 的常量）。
    非蓄力武器 base_time / charge_time 均为 None，乘区恒为 1.0。

    旧实现把系数写死成 1.5（那其实是爱丽丝一人的蓄力时间），并用
    `if name == "小红帽"` 分支打补丁 —— 对其他蓄力角色系数是错的。
    """
    if profile.base_time is None or profile.charge_time is None:
        return 1.0

    effective_cs = min(profile.cs_threshold or 0.0, cs_ol)
    actual_time = profile.base_time - profile.charge_time * effective_cs
    if actual_time < HARD_ANIM_SEC:
        actual_time = HARD_ANIM_SEC
    return 1.0 / actual_time


# ────────────────────────────────────────────────────────────
# 乘区 5：暴击/暴伤 M_Crit（修复版）
# ────────────────────────────────────────────────────────────

def compute_m_crit(cr: float, cd: float) -> float:
    expected_crit_bonus = cr * (0.5 + cd)
    return (2.8 + expected_crit_bonus) / 2.8


# ────────────────────────────────────────────────────────────
# 综合伤害函数 F
# ────────────────────────────────────────────────────────────

@dataclass
class CharSummary:
    atk_pct: float = 0.0
    ele_pct: float = 0.0
    ammo_pct: float = 0.0
    cs_pct: float = 0.0
    cr_pct: float = 0.0
    cd_pct: float = 0.0


# 词条标准名 → CharSummary 字段。单一来源，build_char_summary 与
# bidding_engine._add_to_summary 共用（此前是两处各写一份，容易漂移）。
#
# 未列入的词条（防御力增加/命中率增加/蓄力伤害增加）不参与五大乘区，
# 是当前模型的有意取舍，不是遗漏。
BUFF_TO_SUMMARY_ATTR: dict[str, str] = {
    "攻击力增加": "atk_pct",
    "优越代码伤害增加": "ele_pct",
    "最大装弹数增加": "ammo_pct",
    "蓄力速度增加": "cs_pct",
    "暴击率增加": "cr_pct",
    "暴击伤害增加": "cd_pct",
}


def compute_total_damage_factor(summary: CharSummary, profile: CharPhysicalProfile) -> float:
    m_atk = compute_m_atk(summary.atk_pct)
    m_ele = compute_m_ele(summary.ele_pct)
    m_ammo = compute_m_ammo(summary.ammo_pct, profile)
    m_cs = compute_m_cs(summary.cs_pct, profile)
    m_crit = compute_m_crit(summary.cr_pct, summary.cd_pct)
    return m_atk * m_ele * m_ammo * m_cs * m_crit


def compute_relative_gain(
    before: CharSummary,
    after: CharSummary,
    profile: CharPhysicalProfile,
) -> float:
    f_before = compute_total_damage_factor(before, profile)
    if f_before <= 0:
        return 0.0
    f_after = compute_total_damage_factor(after, profile)
    return f_after / f_before - 1.0


# ────────────────────────────────────────────────────────────
# 从装备列表构建 CharSummary
# ────────────────────────────────────────────────────────────

def build_char_summary(gears: dict) -> CharSummary:
    s = CharSummary()
    for gear in gears.values():
        if gear is None:
            continue
        for line in gear.lines:
            if line.is_empty:
                continue
            bn = line.buff_type
            # 非标准名抛错，不静默跳过。
            #
            # 跳过「合法但未建模」的词条（防御力增加/命中率增加/蓄力伤害增加，
            # 它们不在五大乘区里）是有意取舍；但跳过「根本认不出的名字」就是 bug ——
            # 旧实现正是这样把装弹类收益静默算成 0 的（键名漂移，
            # 见 [[nikke-progress-2026-09-25]]）。
            if bn not in TIER_VALUE_MATRIX:
                raise KeyError(
                    f"装备词条含非标准名 {bn!r}（{gear.slot}）。"
                    f"标准名见 config.BUFF_NAMES；旧写法应在读入时经 buff_aliases 翻译。"
                )
            if bn in BUFF_TO_SUMMARY_ATTR:
                attr = BUFF_TO_SUMMARY_ATTR[bn]
                setattr(s, attr, getattr(s, attr) + line.value_pct / 100.0)
    return s