"""
洗练期望石头数 — 无放回超几何选择 + 几何分布期望

基于 T10装备全局ROI算法DeepResearch.md §2-§4：

1. 槽位激活分布（无锁状态）：
   P(A=1)=0.35, P(A=2)=0.50, P(A=3)=0.15

2. 无放回超几何选择概率：
   P(X=x | A=a) = C(M,x) × C(9-M, a-x) / C(9,a)

3. 洗种类期望成本：
   - 0锁: E[C] = 1 / P_success_0
   - 1锁: E[C] = 2 + 2 / P_success_1
   - 2锁: E[C] = 3 + 3 / P_success_2

4. 洗数值渐进期望：
   k=1: 6.67, k=2: 18.93, k=3: 34.79 (P_high=0.15)
"""

from math import comb
from config import (
    SLOT_ACTIVATION_PROB,
    LOCK_ROLL_COST,
    LOCK_TICKET,
    TOTAL_BUFF_TYPES,
    P_HIGH_TIER,
    VALUE_PURIFY_COST,
)


# ────────────────────────────────────────────────────────────
# 超几何概率核心
# ────────────────────────────────────────────────────────────

def hypergeometric_prob(a: int, m: int, total: int = TOTAL_BUFF_TYPES) -> dict[int, float]:
    """
    无放回超几何选择概率分布。

    从 total 个词条中随机抽取 a 个，其中 m 个为"有效目标"。
    返回 {x: P(X=x)} 字典，x 为有效目标命中数。

    P(X=x) = C(m,x) × C(total-m, a-x) / C(total,a)
    """
    probs = {}
    for x in range(0, min(a, m) + 1):
        if a - x <= total - m:
            probs[x] = comb(m, x) * comb(total - m, a - x) / comb(total, a)
        else:
            probs[x] = 0.0
    return probs


# ────────────────────────────────────────────────────────────
# 槽位激活分布
# ────────────────────────────────────────────────────────────

# 无锁状态下激活槽位数 A 的概率分布
# P(A=1) = 1.0 × 0.5 × 0.7 = 0.35
# P(A=2) = 1.0×0.5×0.7 + 1.0×0.5×0.3 = 0.50
# P(A=3) = 1.0 × 0.5 × 0.3 = 0.15
UNLOCKED_SLOT_DISTRIBUTION = {1: 0.35, 2: 0.50, 3: 0.15}

# 锁 1 后剩余两个槽位的激活分布
# P(A_rem=0) = 0.5 × 0.7 = 0.35
# P(A_rem=1) = 0.5×0.7 + 0.5×0.3 = 0.50
# P(A_rem=2) = 0.5 × 0.3 = 0.15
LOCK1_REMAINING_DISTRIBUTION = {1: 0.50, 2: 0.15}


# ────────────────────────────────────────────────────────────
# 洗词条种类 (Reroll Type) 期望成本
# ────────────────────────────────────────────────────────────

def expected_stones_reroll_type(
    current_targets_on_gear: list[str],
    all_targets: list[str],
) -> float:
    """
    计算在当前装备状态下，通过洗种类增加至少 1 条目标词条的期望石头成本。

    这是全局竞价引擎的核心成本函数。

    Args:
        current_targets_on_gear: 该装备上已有的目标词条列表
        all_targets: 该角色的全部目标词条种类列表

    Returns:
        期望石头消耗；无穷大表示不可能
    """
    m = len(set(all_targets))  # 有效目标词条种类数
    e = len(current_targets_on_gear)  # 该装备已持有的目标词条数

    if e >= 3 or m == 0:
        return float("inf")

    if e == 0:
        # ── 无锁状态：洗出第 1 条目标词条 ──
        p_success = 0.0
        for a, p_a in UNLOCKED_SLOT_DISTRIBUTION.items():
            probs = hypergeometric_prob(a, m)
            # 成功 = 至少命中 1 条目标
            p_success += p_a * (1.0 - probs.get(0, 0.0))
        if p_success <= 0:
            return float("inf")
        return 1.0 / p_success

    elif e == 1:
        # ── 锁 1 洗 2：洗出第 2 条目标词条 ──
        remaining_m = m - 1  # 已锁 1 条，候选池缩小
        p_success = 0.0
        for a_rem, p_a in LOCK1_REMAINING_DISTRIBUTION.items():
            probs = hypergeometric_prob(a_rem, remaining_m, total=8)
            p_success += p_a * (1.0 - probs.get(0, 0.0))
        if p_success <= 0:
            return float("inf")
        # 期望 = 锁词门票(2) + 期望洗练次数 × 每次成本(2)
        return LOCK_TICKET[1] + LOCK_ROLL_COST[1] / p_success

    elif e == 2:
        # ── 锁 2 洗 1：洗出第 3 条目标词条 ──
        # 仅剩槽位 3，激活概率 30%
        p_success = SLOT_ACTIVATION_PROB[2] * (m - 2) / 7.0
        if p_success <= 0:
            return float("inf")
        # 期望 = 锁词门票(3) + 期望洗练次数 × 每次成本(3)
        return LOCK_TICKET[2] + LOCK_ROLL_COST[2] / p_success

    return float("inf")


# ────────────────────────────────────────────────────────────
# 洗词条数值 (Reroll Value) 期望成本
# ────────────────────────────────────────────────────────────

def expected_stones_reroll_value(num_low_tier_slots: int) -> float:
    """
    渐进式数值提纯的期望石头成本。

    当装备有 k 条有效词条但档位偏低时，将它们全部提纯至 Tier 11+
    的期望总成本。

    Args:
        num_low_tier_slots: 该装备上档位低于 Tier 11 的有效词条数 (1-3)

    Returns:
        期望石头消耗
    """
    return VALUE_PURIFY_COST.get(num_low_tier_slots, 34.79)


# ────────────────────────────────────────────────────────────
# 白板开光（未过载装备）成本
# ────────────────────────────────────────────────────────────

def expected_stones_first_activation() -> float:
    """T9→T10 过载开光固定消耗 1 颗石头"""
    return 1.0


# ────────────────────────────────────────────────────────────
# 辅助：装备目标词条统计
# ────────────────────────────────────────────────────────────

def count_targets_on_gear(gear_lines: list, target_set: set[str]) -> list[str]:
    """
    返回该装备上已存在的目标词条列表（去重后的词条名）。

    Args:
        gear_lines: BuffLine 列表
        target_set: 目标词条名称集合
    """
    found = []
    for line in gear_lines:
        if not line.is_empty and line.buff_type in target_set:
            if line.buff_type not in found:
                found.append(line.buff_type)
    return found


def count_low_tier_targets(gear_lines: list, target_set: set[str]) -> int:
    """
    统计该装备上目标词条中档位低于 Tier 11 的数量。

    Args:
        gear_lines: BuffLine 列表
        target_set: 目标词条名称集合
    """
    count = 0
    for line in gear_lines:
        if not line.is_empty and line.buff_type in target_set and line.tier < 11:
            count += 1
    return count

# engine/probability.py（新增部分）

def expected_cost_to_achieve_targets(
    current_targets_on_gear: list[str],
    target_set: set[str],
) -> float:
    """
    计算从当前状态达到目标词条集合的期望总石头成本。
    采用递归动态规划，每步选择最优顺序（先洗哪个词条）。
    当前仅支持目标集合大小 ≤ 3 且当前已拥有词条均为目标的子集。
    """
    current_set = set(current_targets_on_gear)
    # 过滤：只保留与目标集合相关的当前词条
    current_relevant = current_set & target_set
    already_have = len(current_relevant)
    target_size = len(target_set)
    
    if already_have >= target_size:
        return 0.0
    
    # 递归计算
    from functools import lru_cache
    
    @lru_cache(None)
    def dp(have: int) -> float:
        if have >= target_size:
            return 0.0
        # 当前锁定数 = have
        if have == 0:
            # 无锁，目标池大小 = target_size（全部目标）
            p_success = 0.0
            for a, p_a in UNLOCKED_SLOT_DISTRIBUTION.items():
                probs = hypergeometric_prob(a, target_size)  # 从9个中抽a个，命中至少1个目标
                p_success += p_a * (1.0 - probs.get(0, 0.0))
            if p_success <= 0:
                return float('inf')
            cost_step = 1.0 / p_success  # 滚动成本1
            return cost_step + dp(have + 1)
        elif have == 1:
            # 锁1，剩余目标数 = target_size - 1
            remaining_m = target_size - 1
            p_success = 0.0
            for a_rem, p_a in LOCK1_REMAINING_DISTRIBUTION.items():
                probs = hypergeometric_prob(a_rem, remaining_m, total=8)
                p_success += p_a * (1.0 - probs.get(0, 0.0))
            if p_success <= 0:
                return float('inf')
            cost_step = LOCK_TICKET[1] + LOCK_ROLL_COST[1] / p_success
            return cost_step + dp(have + 1)
        elif have == 2:
            # 锁2，剩余目标数 = target_size - 2
            remaining_m = target_size - 2
            if remaining_m <= 0:
                return 0.0
            p_success = SLOT_ACTIVATION_PROB[2] * (remaining_m / 7.0)
            if p_success <= 0:
                return float('inf')
            cost_step = LOCK_TICKET[2] + LOCK_ROLL_COST[2] / p_success
            return cost_step + dp(have + 1)
        else:
            return float('inf')
    
    return dp(already_have)