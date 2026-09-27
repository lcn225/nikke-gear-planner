"""
全局竞价大排队引擎 (Global Bidding Engine) — 方案级重构

核心竞价公式：
    ROI = 期望收益 / 期望成本

每个候选动作是一个明确的"目标状态"：
    - 开光（T9→T10）
    - 装备等级强化（消耗信用点）
    - 达成特定词条目标组合（如 {蓄力速度}、{蓄力速度, 优越代码} 等）

所有动作投入统一降序大排队 => 单一混合竞价天梯榜。
"""

from dataclasses import dataclass, field
from typing import Optional, List, Set, Dict
from itertools import combinations
from models.character import Character
from models.gear import Gear
from engine.damage_model import (
    BUFF_TO_SUMMARY_ATTR,
    CharPhysicalProfile,
    CharSummary,
    get_profile,
    build_char_summary,
    compute_relative_gain,
    compute_m_atk_upgrade,
)
from engine.probability import (
    expected_stones_first_activation,
    expected_cost_to_achieve_targets,
    count_targets_on_gear,
)
from models.targets import panel_progress, primary_progress
from config import (
    SHADOW_PRICE_LAMBDA,
    UPGRADE_CREDIT_COST,
    UPGRADE_ATK_GAIN,
    BASE_CHAR_ATK,
    GEAR_SLOTS,
    get_tier_value,
    get_tier11_value,
    P_HIGH_TIER,
    TIER_WEIGHT_Q,
    tier_rank,
)


# 毕业进度一节最多列几个角色。40+ 个全列出来会把报告淹掉，
# 而「离毕业多远」这个问题，答案通常是差一两条的那几个。
PROGRESS_LIMIT = 15


@dataclass
class CharacterRow:
    """
    角色榜的一行 = 一个角色的「下一步」。

    为什么按角色成行，而不是把 1400 多条明细平铺：用户的问题是
    「我现在该把资源用到哪」，答案是**某个角色的某件事**，不是
    「第 303 顺位那条洗练」。平铺还会让档位靠前的角色被自己的
    几十条候选刷屏，把别的角色挤出视野。
    """
    rank: int = 0
    name: str = ""
    tier: str = ""
    weight: float = 1.0
    graduated: bool = False
    # 字符串注解：BidEntry 定义在下面，直接写会在此刻求值时 NameError
    best: Optional["BidEntry"] = None
    n_actions: int = 0
    progress: List[dict] = field(default_factory=list)
    unmet_primary: List[str] = field(default_factory=list)
    # 没有候选动作时说明原因。区分「真的没事可做」和「算不了」——
    # 前者是结论，后者是数据缺口，混成一句「无候选动作」就是报表在撒谎。
    no_action_reason: str = ""

    @property
    def progress_summary(self) -> str:
        """紧凑的毕业进度：达标数 + 缺口最大那一项。"""
        if not self.progress:
            return "无面板"
        done = sum(1 for r in self.progress if r["done"])
        total = len(self.progress)
        if done == total:
            return f"🎓 {done}/{total}"
        worst = max((r for r in self.progress if not r["done"]), key=lambda r: r["gap"])
        return (f"{done}/{total} · {worst['buff']} "
                f"{worst['have']:.0f}→{worst['want']:.0f}")


@dataclass
class BidEntry:
    """单条全局竞价条目"""
    priority: int = 0
    character_name: str = ""
    gear_slot: str = ""
    action_type: str = ""          # "开光" / "升级" / "洗词条" / "洗数值" / "洗词条+洗数值"
    target_set: Set[str] = None    # 仅对词条方案有效，表示目标词条集合
    equivalent_cost: float = 0.0
    expected_damage_gain: float = 0.0
    roi: float = 0.0
    action_detail: str = ""
    resource_desc: str = ""
    # primary 未达成 → 该候选被角色级门禁拦住。
    # 仍按 ROI 参与排序并列出（不丢信息），只是标注出来，见 GlobalBiddingEngine。
    gated: bool = False
    # 角色培养档位与其权重（config.tier_weight）。跨角色比较时必须折算：
    # ΔB 是「该角色自身伤害」的增幅，不折算会让仓管排到主力前面。
    tier: str = ""
    tier_weight: float = 1.0
    # 排序分 = roi × tier_weight × 库存折减。roi 保持原值（ΔB/ΔC）不动，
    # 这样报告里能同时看到「原始 ROI」和「折算后的排序分」，可审计。
    sort_score: float = 0.0


@dataclass
class TargetState:
    """统一的目标状态：词条集合 + 最低档位要求"""
    targets: Set[str]           # 词条种类集合
    min_tier: Optional[int]     # 最低档位要求（None=洗出即可, 11=提到Tier11+）


class GlobalBiddingEngine:
    def __init__(self, stones_held: int = 0, credits_held: int = 0):
        self.stones_held = stones_held
        self.credits_held = credits_held
        # 角色名 -> 未达成的 primary 目标描述。跑完一次后可供报告使用。
        self.unmet_primary: Dict[str, List[str]] = {}

    # ── primary 门禁（角色级）──

    def _unmet_primary(self, char: Character, profile: CharPhysicalProfile) -> List[str]:
        """
        该角色还没达成的 primary 目标。

        判据：每个 primary 词条在全套 4 件装备里的**件数** ≥ 它自己声明的下限
        （`*N` 与 `（至少N条）` 取 N；「任意」「越多越好」「裸名」取 1）。

        为什么放角色级：件数配额（`装弹*3`）和毕业面板本来就是**全套**口径，
        拆到单件上「单件最多 1 条」，配额语义就没了。
        """
        unmet = []
        for spec in profile.primary:
            have = char.count_buff_across_all(spec.buff)
            if have < spec.floor:
                unmet.append(f"{spec.buff} {have}/{spec.floor}")
        return unmet

    def run(self, characters: List[Character]) -> List[BidEntry]:
        all_bids = []
        # 角色 -> 该角色的 primary 词条集合（用于判定某条竞价是不是纯副目标）
        primary_sets: Dict[str, Set[str]] = {}
        open_for: Dict[str, bool] = {}
        char_weight: Dict[str, float] = {}
        char_tier: Dict[str, str] = {}

        for char in characters:
            profile = get_profile(char.name, char.targets)
            if profile is None:
                continue

            unmet = self._unmet_primary(char, profile)
            self.unmet_primary[char.name] = unmet
            primary_sets[char.name] = {s.buff for s in profile.primary}
            open_for[char.name] = not unmet
            char_weight[char.name] = char.targets.weight if char.targets else 1.0
            char_tier[char.name] = char.targets.tier if char.targets else ""

            for slot in GEAR_SLOTS:
                gear = char.gears.get(slot)
                bids = self._evaluate_gear(char, gear, slot, profile)
                all_bids.extend(bids)

        # ── primary 门禁：未达成时拦住**纯 secondary** 的候选 ──
        # 不丢弃、不调 ROI：照常参与排序并列出，只打标记。
        # 调 ROI 就等于引入主观系数；丢弃则让人看不见「做完 primary 之后是什么」。
        for bid in all_bids:
            if open_for.get(bid.character_name, True):
                continue
            if not bid.target_set:
                continue          # 开光/升级是前置动作，不受门禁
            if bid.target_set & primary_sets.get(bid.character_name, set()):
                continue          # 这条本身就含主目标，放行
            bid.gated = True

        # ── 跨角色折算 + 库存红线折减 ──
        # 两件事都只进 sort_score，不覆盖 roi —— 报告要能同时显示原始 ROI
        # 和折算后的排序分，否则「为什么这条 ROI 更高却排在后面」无法自查。
        for bid in all_bids:
            w = char_weight.get(bid.character_name, 1.0)
            bid.tier = char_tier.get(bid.character_name, "")
            bid.tier_weight = w
            discount = 1.0
            if self.stones_held > 0 and bid.equivalent_cost > 0:
                discount = min(1.0, self.stones_held / bid.equivalent_cost)
            bid.sort_score = bid.roi * w * discount

        all_bids.sort(key=lambda b: b.sort_score, reverse=True)
        for i, bid in enumerate(all_bids):
            bid.priority = i + 1
        return all_bids

    def _evaluate_gear(
        self, char: Character, gear: Optional[Gear], slot: str, profile: CharPhysicalProfile
    ) -> List[BidEntry]:
        bids = []
        current_summary = build_char_summary(char.gears)

        # 判断是否已过载
        is_overgeared = gear is not None and gear.empty_slot_count() < 3

        # ── 路径 A: 白板开光 ──
        if not is_overgeared:
            bid = self._make_activation_bid(char, slot, profile, current_summary)
            if bid:
                bids.append(bid)
            # 未过载的装备不生成其他方案（除非是白板升级，但升级需要先过载）
            if gear is None:
                return bids
            if gear.level < 5:
                bid = self._make_upgrade_bid(char, gear, slot, profile, current_summary)
                if bid:
                    bids.append(bid)
            return bids

        # ── 路径 B: 升级 ──
        if gear.level < 5:
            bid = self._make_upgrade_bid(char, gear, slot, profile, current_summary)
            if bid:
                bids.append(bid)

        # ── 路径 C: 方案级词条目标 ──
        targets_on_gear = set(count_targets_on_gear(gear.lines, set(profile.targets)))
        # 生成候选目标状态（洗词条 + 洗数值 + 混合）
        states = self._enumerate_target_states(gear, profile, targets_on_gear)
        for state in states:
            bid = self._make_plan_bid(char, gear, slot, profile, current_summary, state)
            if bid:
                bids.append(bid)

        return bids

    # ── 辅助：生成有意义的词条目标状态 ──

    def _get_tier_on_gear(self, gear: Optional[Gear], buff_name: str) -> int:
        """返回指定词条在该装备上的档位（1-15），不存在则返回 0"""
        if gear is None:
            return 0
        for line in gear.lines:
            if not line.is_empty and line.buff_type == buff_name:
                return line.tier
        return 0

    def _enumerate_target_states(self, gear: Gear, profile: CharPhysicalProfile, current_have: Set[str]) -> List[TargetState]:
        """
        为单个装备部位生成所有有意义的目标状态。
        三类：
          1. 洗词条 — 从缺失词条中取 1~3 个组合，min_tier=None（洗出即可）
          2. 洗数值 — 每个已有低档词条单独提纯到 T11+
          3. 混合   — 已有低档词条 + 缺失词条的配对，全部要求 T11+
        """
        all_targets = set(profile.targets)
        missing = sorted(all_targets - current_have)
        existing_low = [t for t in current_have if self._get_tier_on_gear(gear, t) < 11]

        states: List[TargetState] = []

        # 1. 洗词条类：缺失词条的 1~3 组合，档位不要求（洗出即可）
        max_k = min(len(missing), 3)
        for k in range(1, max_k + 1):
            for combo in combinations(missing, k):
                states.append(TargetState(targets=set(combo), min_tier=None))

        # 2. 洗数值类：每个已有低档词条单独提纯到 T11+
        for t in existing_low:
            states.append(TargetState(targets={t}, min_tier=11))

        # 3. 混合类：已有低档 + 缺失词条配对，全部要求 T11+
        for low_t in existing_low:
            for miss_t in missing:
                states.append(TargetState(targets={low_t, miss_t}, min_tier=11))

        # 4. 多个低档词条同时提纯
        if len(existing_low) >= 2:
            states.append(TargetState(targets=set(existing_low), min_tier=11))

        return states

    # ── Path A: 白板开光 ──

    def _make_activation_bid(
        self, char: Character, slot: str, profile: CharPhysicalProfile, current: CharSummary
    ) -> Optional[BidEntry]:
        delta_c = expected_stones_first_activation()
        # 模拟获得一条任意目标词条（取中档值）的收益
        # 实际玩家开光后可能得到多种词条，但我们这里取最佳预期？更稳妥的是取所有目标词条的平均收益
        # 为了简化，我们模拟获得一个"平均目标词条"的收益
        # 实际上，我们可以枚举所有目标词条，取最大收益作为"最佳开光"预期，但开光时词条是随机的，所以应该用概率加权平均
        # 这里采用加权平均：每个目标词条出现概率相同（超几何下等概率），取平均值
        total_gain = 0.0
        count = 0
        for target in profile.targets:
            sim_val = get_tier11_value(target) / 100.0
            sim_after = _copy_summary(current)
            _add_to_summary(sim_after, target, sim_val)
            gain = compute_relative_gain(current, sim_after, profile)
            total_gain += gain
            count += 1
        avg_gain = total_gain / count if count > 0 else 0.0
        if avg_gain <= 0:
            return None
        roi = avg_gain / delta_c
        return BidEntry(
            character_name=char.name,
            gear_slot=slot,
            action_type="开光",
            equivalent_cost=delta_c,
            expected_damage_gain=avg_gain,
            roi=roi,
            action_detail=f"将 {char.name} 的闲置T9企业【{slot}】部装备过载激活，期望首条目标词条",
            resource_desc=f"期望 {delta_c:.1f} 石头",
        )

    # ── Path B: 升级 ──

    def _make_upgrade_bid(
        self, char: Character, gear: Gear, slot: str, profile: CharPhysicalProfile, current: CharSummary
    ) -> Optional[BidEntry]:
        level = gear.level
        if level >= 5:
            return None
        cost_credits = UPGRADE_CREDIT_COST.get(level, 0)
        delta_c = cost_credits / SHADOW_PRICE_LAMBDA
        atk_gain = UPGRADE_ATK_GAIN.get(slot, 0.0)
        if not profile.is_attacker or atk_gain <= 0:
            return None
        delta_b = atk_gain / BASE_CHAR_ATK
        if delta_b <= 0:
            return None
        roi = delta_b / delta_c
        return BidEntry(
            character_name=char.name,
            gear_slot=slot,
            action_type="升级",
            equivalent_cost=delta_c,
            expected_damage_gain=delta_b,
            roi=roi,
            action_detail=f"消耗 {cost_credits/1000:.0f}k 信用点强化{slot}部基础攻击面板 (Lv{level}→Lv{level+1})",
            resource_desc=f"{cost_credits/10000:.1f}万 信用点 (≈{delta_c:.2f} 等效石头)",
        )

    # ── Path C: 方案级词条目标（统一目标状态） ──

    def _compute_state_cost(self, gear: Gear, targets: Set[str], min_tier: Optional[int],
                            profile: CharPhysicalProfile) -> float:
        """
        计算达成目标状态的期望总石头成本。
        分两步：先洗出缺失词条（DP），再提纯已有低档词条（几何分布 + 锁定成本）。
        """
        current_on_gear = set(count_targets_on_gear(gear.lines, set(profile.targets)))
        need_to_wash = [t for t in targets if t not in current_on_gear]
        need_to_purify = [
            t for t in targets
            if t in current_on_gear and self._get_tier_on_gear(gear, t) < (min_tier or 0)
        ]

        total_cost = 0.0
        current_have = set(current_on_gear)

        # Phase 1: 洗出缺失词条（从当前已有状态逐步洗到目标）
        for t in need_to_wash:
            cost = expected_cost_to_achieve_targets(list(current_have), {t})
            if cost <= 0 or cost == float('inf'):
                return float('inf')
            total_cost += cost
            current_have.add(t)

        # Phase 2: 提纯已有低档词条（变更数值，锁定其他词条）
        for t in need_to_purify:
            # 锁定除当前提纯目标外的所有已有目标词条
            locked_count = len(current_have) - 1
            roll_cost = max(1, locked_count + 1)   # 锁 N 条后每次重掷消耗 N+1 石
            expected_rolls = 1.0 / P_HIGH_TIER     # P(T11+) = 0.15 → 期望 6.67 次
            total_cost += roll_cost * expected_rolls

        return total_cost

    def _compute_state_gain(self, current_summary: CharSummary, gear: Gear,
                            targets: Set[str], min_tier: Optional[int],
                            profile: CharPhysicalProfile) -> float:
        """计算达成目标状态后的相对伤害增幅 ΔB"""
        sim_after = _copy_summary(current_summary)
        target_tier = min_tier if min_tier is not None else 11  # 新词条默认瞄准 T11

        for t in targets:
            current_tier = self._get_tier_on_gear(gear, t)
            current_val = get_tier_value(t, current_tier) if current_tier > 0 else 0.0
            target_val = get_tier_value(t, target_tier)
            delta = (target_val - current_val) / 100.0
            if delta > 0:
                _add_to_summary(sim_after, t, delta)

        return compute_relative_gain(current_summary, sim_after, profile)

    def _make_plan_bid(
        self, char: Character, gear: Gear, slot: str, profile: CharPhysicalProfile,
        current: CharSummary, target_state: TargetState
    ) -> Optional[BidEntry]:
        """基于目标状态生成竞价条目"""
        targets = target_state.targets
        min_tier = target_state.min_tier

        # 计算期望成本
        expected_cost = self._compute_state_cost(gear, targets, min_tier, profile)
        if expected_cost <= 0 or expected_cost == float('inf'):
            return None

        # 计算期望收益
        delta_b = self._compute_state_gain(current, gear, targets, min_tier, profile)
        if delta_b <= 0:
            return None

        roi = delta_b / expected_cost
        target_str = "+".join(sorted(targets))

        # 判断动作类型
        current_on_gear = set(count_targets_on_gear(gear.lines, set(profile.targets)))
        targets_on_gear = targets & current_on_gear
        targets_missing = targets - current_on_gear

        if not targets_missing:
            # 所有目标词条已存在，仅提纯档位 → 洗数值
            action_type = "洗数值"
        elif not targets_on_gear:
            # 所有目标词条均缺失，洗出新词条 → 洗词条
            action_type = "洗词条"
        else:
            # 混合 → 洗词条+洗数值
            action_type = "洗词条+洗数值"

        # 构建详情文本
        if min_tier is not None:
            detail = f"对{char.name}【{slot}】部达成目标 {target_str} (≥T{min_tier})"
        else:
            detail = f"对{char.name}【{slot}】部洗练至达成目标 {target_str}"

        return BidEntry(
            character_name=char.name,
            gear_slot=slot,
            action_type=action_type,
            target_set=targets,
            equivalent_cost=expected_cost,
            expected_damage_gain=delta_b,
            roi=roi,
            action_detail=detail,
            resource_desc=f"期望 {expected_cost:.1f} 石头",
        )


# ── 辅助函数 ──

def _copy_summary(s: CharSummary) -> CharSummary:
    return CharSummary(
        atk_pct=s.atk_pct, ele_pct=s.ele_pct, ammo_pct=s.ammo_pct,
        cs_pct=s.cs_pct, cr_pct=s.cr_pct, cd_pct=s.cd_pct,
    )

def _add_to_summary(s: CharSummary, buff_name: str, delta: float):
    """把一条词条的增量加进乘区快照。映射表与 build_char_summary 共用一份。"""
    if buff_name in BUFF_TO_SUMMARY_ATTR:
        attr = BUFF_TO_SUMMARY_ATTR[buff_name]
        setattr(s, attr, getattr(s, attr) + delta)


# ── 角色榜 ──

def build_character_ladder(
    characters: List[Character],
    bids: List[BidEntry],
    unmet_primary: Optional[Dict[str, List[str]]] = None,
    include_graduated: bool = False,
    unavailable: Optional[Dict[str, str]] = None,
) -> List[CharacterRow]:
    """
    一角色一行的培养榜。

    排序：**档位优先，档内按该角色的最优动作 ROI 降序**。
    为什么不是 ROI×权重 一把梭：那样 T2/T3 的便宜动作会插到 T0 前面
    （实测 T3 的尼恩：蓝色海洋能排到第 9），而 T0 是永久保质期的角色，
    投进去的每分资源都有回报 —— 档位必须作为**次序**先起作用。

    为什么不会因此「死磕 T0 的最后一个词条」：一行一角色，T0 的占位
    被压到「T0 的角色数」（实测 4 行），看完自然往下走。平铺明细才会有
    这个问题 —— 那才是当初想分档排序时的顾虑。
    """
    unmet_primary = unmet_primary or {}
    unavailable = unavailable or {}
    best_by_char: Dict[str, BidEntry] = {}
    count_by_char: Dict[str, int] = {}
    for b in bids:
        count_by_char[b.character_name] = count_by_char.get(b.character_name, 0) + 1
        cur = best_by_char.get(b.character_name)
        if cur is None or b.sort_score > cur.sort_score:
            best_by_char[b.character_name] = b

    rows: List[CharacterRow] = []
    for char in characters:
        if char.targets is None:
            continue
        progress = panel_progress(char, char.targets)
        unmet = unmet_primary.get(char.name, [])
        graduated = (not unmet) and all(r["done"] for r in progress)
        if graduated and not include_graduated:
            continue

        best = best_by_char.get(char.name)
        reason = ""
        if best is None:
            reason = unavailable.get(char.name) or "已无待办动作"
        rows.append(CharacterRow(
            name=char.name,
            tier=char.targets.tier,
            weight=char.targets.weight,
            graduated=graduated,
            best=best,
            n_actions=count_by_char.get(char.name, 0),
            progress=progress,
            unmet_primary=unmet,
            no_action_reason=reason,
        ))

    # 档位优先；档内按最优动作的排序分。没有动作的（如纯「无需」角色）
    # 排在档位组内最后，但仍在榜上 —— 「不用管」本身也是结论。
    rows.sort(key=lambda r: (
        tier_rank(r.tier),
        -(r.best.sort_score if r.best else -1.0),
        r.name,
    ))
    for i, r in enumerate(rows):
        r.rank = i + 1
    return rows


def build_character_detail(
    name: str,
    characters: List[Character],
    bids: List[BidEntry],
    unmet_primary: Optional[Dict[str, List[str]]] = None,
) -> dict:
    """
    单个角色的展开详情（角色榜点开某一行时显示）。

    纯函数、不碰任何 UI 框架 —— 和 character_rows_to_records 一个道理：
    渲染层只负责画，文案与结构在这里定，免得 CLI/GUI 各写一遍后走偏。

    Returns: 找不到该角色（或它没有养成目标）时返回 {}。
    """
    char = next((c for c in characters if c.name == name), None)
    if char is None or char.targets is None:
        return {}

    unmet_primary = unmet_primary or {}
    actions = [b for b in bids if b.character_name == name]
    return {
        "name": name,
        "tier": char.targets.tier,
        "weight": char.targets.weight,
        "unmet": unmet_primary.get(name, []),
        "primary": primary_progress(char, char.targets),
        "panel": panel_progress(char, char.targets),
        "panel_directives": list(char.targets.panel_directives),
        "actions": actions,
        "n_actions": len(actions),
    }


def character_rows_to_records(rows: List[CharacterRow]) -> List[dict]:
    """
    角色榜 → 扁平记录。**纯函数，不依赖任何表格库。**

    Markdown 报表和 GUI 的 DataFrame 都从这里取，避免两条路各写一遍
    单元格文案 —— 那种重复迟早会让「CLI 显示 ⏸ 但 GUI 不显示」。
    """
    out = []
    for r in rows:
        rec = {
            "顺位": r.rank,
            "角色": r.name,
            "档位": f"T{r.tier}" if r.tier else "—",
            "毕业进度": r.progress_summary,
            "候选数": r.n_actions,
            "gated": False,
        }
        if r.best is None:
            rec.update({
                "下一步": f"—（{r.no_action_reason}）" if r.no_action_reason else "—",
                "成本(石)": None,
                "ROI": None,
            })
        else:
            tgt = "+".join(sorted(r.best.target_set)) if r.best.target_set else ""
            rec.update({
                "下一步": f"{'⏸ ' if r.best.gated else ''}"
                          f"{r.best.action_type} {r.best.gear_slot} {tgt}".strip(),
                "成本(石)": round(r.best.equivalent_cost, 2),
                "ROI": round(r.best.roi, 4),
                "gated": r.best.gated,
            })
        out.append(rec)
    return out


def generate_character_ladder_report(
    rows: List[CharacterRow],
    stones_held: int = 0,
    credits_held: int = 0,
) -> str:
    """角色榜 Markdown。一行 = 一个角色的下一步。"""
    if not rows:
        return "🎉 所有角色已毕业，暂无培养动作！"

    parts = [
        "## 🏆 角色培养榜（未毕业 · 档位优先）\n",
        "> 一行 = 一个角色的**下一步**。排序：**档位优先，档内按该角色最优动作的 ROI**。\n"
        "> T0 是永久保质期角色，投进去的每分资源都有回报，所以档位作为次序先起作用，"
        "而不是被 T2/T3 的便宜动作插队。\n",
        "| 顺位 | 角色 | 档位 | 下一步 | 成本(石) | ROI | 毕业进度 |",
        "|------|------|------|--------|----------|-----|----------|",
    ]

    for rec in character_rows_to_records(rows):
        cost = "—" if rec["成本(石)"] is None else f"{rec['成本(石)']:.1f}"
        roi = "—" if rec["ROI"] is None else f"{rec['ROI']:.4f}"
        parts.append(
            f"| {rec['顺位']} | {rec['角色']} | {rec['档位']} | {rec['下一步']} "
            f"| {cost} | {roi} | {rec['毕业进度']} |"
        )

    return "\n".join(parts)


# ── 输出格式化（保持不变，但需要适配新增的 target_set 字段） ──

def generate_unified_ladder_report(
    bids: List[BidEntry],
    stones_held: int = 0,
    credits_held: int = 0,
    top_n: int = 0,
    characters: Optional[List[Character]] = None,
    unmet_primary: Optional[Dict[str, List[str]]] = None,
    with_progress: bool = True,
) -> str:
    """
    生成单一全局竞价天梯 Markdown 报告。

    Args:
        characters: 传入则多输出「毕业进度」（panel 当前值 vs 目标值）
        unmet_primary: GlobalBiddingEngine.unmet_primary，用于列出待突破的主目标
        with_progress: 关掉可省掉毕业进度那一节
    """
    if not bids:
        return "🎉 所有角色装备已完美毕业，暂无竞价动作！"

    parts = []

    # ── 库存概览 ──
    parts.append("## 📦 库存概览")
    parts.append(f"- 自定义模块石头：**{stones_held}** 颗")
    parts.append(f"- 信用点：**{credits_held:,}**")
    total_equiv = stones_held + credits_held / SHADOW_PRICE_LAMBDA
    parts.append(f"- 等效石头总量：**{total_equiv:.1f}** 石 (含信用点折合)\n")

    # ── 门禁：主目标还没达成的角色 ──
    gated_n = sum(1 for b in bids if b.gated)
    if unmet_primary:
        blocked = {n: u for n, u in unmet_primary.items() if u}
        if blocked:
            parts.append("## 🚧 待突破的主目标（核心词条未齐）\n")
            parts.append(
                "> 这些角色的 **核心词条还没达到攻略要求的件数**，"
                "所以涉及副目标的候选被标了 **⏸**。\n"
                "> 门禁只影响顺序，不改变 ROI —— 标 ⏸ 的条目照常列出来，"
                "让你看得见「做完主目标之后下一顺位是什么」。\n"
            )
            for name, u in sorted(blocked.items(), key=lambda kv: -len(kv[1])):
                parts.append(f"- **{name}**：{', '.join(u)}")
            parts.append("")

    # ── 单一全局竞价天梯 ──
    parts.append("## 🏆 全局竞价天梯（单一混合降序队列）\n")
    parts.append("> 竞价公式：**ROI = ΔB / ΔC** — 所有动作按 ROI 降序排位，无分榜。")
    parts.append(
        f"> **顺位 = ROI × 档位权重 × 库存折减**。ROI 列保持原始值，"
        f"档位列给出倍率（q={TIER_WEIGHT_Q}，见 config.tier_weight），两者相乘即顺位依据。"
    )
    if gated_n:
        parts.append(f"> 标 **⏸** 的 {gated_n} 条属于「主目标未达成」的角色，建议先做它们的 🚧 部分。")
    parts.append("")

    # 表头
    header = (
        "| 顺位 | 角色 | 档位 | 部位 | 类型 | 目标组合 "
        "| 等效成本(石) | ΔB 伤害增幅 | ROI | 资源警告 |"
    )
    sep = (
        "|------|------|------|------|------|----------"
        "|-------------|------------|-----|----------|"
    )
    parts.append(header)
    parts.append(sep)

    # 截取 top_n
    display_bids = bids[:top_n] if top_n > 0 else bids

    for bid in display_bids:
        target_str = "+".join(sorted(bid.target_set)) if bid.target_set else "—"
        # 格式化 ROI（科学计数法小值转为可读格式）
        if bid.roi >= 0.01:
            roi_str = f"{bid.roi:.4f}"
        elif bid.roi >= 0.0001:
            roi_str = f"{bid.roi:.6f}"
        else:
            roi_str = f"{bid.roi:.2e}"

        delta_b_pct = bid.expected_damage_gain * 100
        if delta_b_pct >= 0.01:
            db_str = f"{delta_b_pct:.2f}%"
        elif delta_b_pct >= 0.0001:
            db_str = f"{delta_b_pct:.4f}%"
        else:
            db_str = f"{delta_b_pct:.2e}%"

        # 操作类型图标
        icon_map = {"开光": "🔵", "升级": "🟢", "洗词条": "🟡", "洗数值": "🟠", "洗词条+洗数值": "🟣"}
        icon = icon_map.get(bid.action_type, "⚪")

        # 资源警告
        if stones_held > 0 and bid.equivalent_cost > stones_held * 0.8:
            if bid.equivalent_cost > stones_held:
                warn_str = "🔴 库存不足"
            else:
                warn_str = "⚠️ 逼近红线"
        else:
            warn_str = "—"

        gate_str = "⏸ " if bid.gated else ""
        # 档位写出来，好让「为什么这条 ROI 更高却排在后面」可以自查：
        # 顺位 = ROI × 档位权重 × 库存折减。
        tier_str = f"×{bid.tier_weight:.2f}" if bid.tier else "—"
        row = (
            f"| {gate_str}{bid.priority} | {bid.character_name} | {tier_str} "
            f"| {bid.gear_slot} | {icon} {bid.action_type} | {target_str} "
            f"| {bid.equivalent_cost:.1f} | {db_str} | {roi_str} "
            f"| {warn_str} |"
        )
        parts.append(row)

    # ── 毕业进度（panel，纯展示）──
    if with_progress and characters:
        rows_by_char = []
        for char in characters:
            if not char.targets or not char.targets.panel:
                continue
            rows = panel_progress(char, char.targets)
            if not rows:
                continue
            # 完成度 = 各项 min(当前/目标, 1) 的均值。只用于**排序展示**，
            # 不参与任何判定 —— 引擎排序仍由 ROI 决定。
            done_n = sum(1 for r in rows if r["done"])
            ratio = sum(min(r["have"] / r["want"], 1.0) if r["want"] else 1.0
                        for r in rows) / len(rows)
            rows_by_char.append((ratio, done_n, len(rows), char, rows))

        if rows_by_char:
            # 最接近毕业的排前面 —— 「我离毕业还有多远」这个问题，
            # 答案通常是「差一两条的那几个」，不是差距最大的那些。
            rows_by_char.sort(key=lambda t: (-t[0], -t[1], t[3].name))
            parts.append("\n## 🎓 毕业进度（推荐面板 vs 当前）\n")
            parts.append(
                "> 面板是攻略给的**毕业状态**（终点），数字是当前装备的该词条总量。\n"
                "> **纯展示，不参与竞价判定** —— 排序仍由 ROI 决定。按完成度降序。\n"
            )
            shown = rows_by_char[:PROGRESS_LIMIT]
            for ratio, done_n, total, char, rows in shown:
                # 用标准名原样显示。不在这里造简称 —— 那会变成第四套命名，
                # 而词条名的翻译只允许发生在 buff_aliases.py 那一层。
                cells = " / ".join(
                    f"{'✅' if r['done'] else ''}{r['buff']} "
                    f"{r['have']:.0f}%→{r['want']:.0f}%"
                    for r in rows
                )
                mark = "🎓" if done_n == total else "　"
                parts.append(f"- {mark} **{char.name}**（{done_n}/{total}）: {cells}")
            if len(rows_by_char) > PROGRESS_LIMIT:
                rest = len(rows_by_char) - PROGRESS_LIMIT
                parts.append(f"- …另有 **{rest}** 个角色面板未达标，此处从略")

    # ── 统计摘要 ──
    parts.append(f"\n## 📊 统计摘要\n")
    parts.append(f"- 总竞价条目：**{len(bids)}** 条")
    if top_n > 0:
        parts.append(f"- 当前显示：前 **{top_n}** 条")

    # 按类型统计
    type_counts: dict[str, int] = {}
    type_roi_max: dict[str, float] = {}
    type_roi_min: dict[str, float] = {}
    for b in bids:
        t = b.action_type
        type_counts[t] = type_counts.get(t, 0) + 1
        type_roi_max[t] = max(type_roi_max.get(t, 0.0), b.roi)
        type_roi_min[t] = min(type_roi_min.get(t, float('inf')), b.roi)

    for t in ["开光", "升级", "洗词条", "洗数值", "洗词条+洗数值"]:
        if t in type_counts:
            parts.append(
                f"- **{t}**：{type_counts[t]} 条，"
                f"ROI 范围 [{type_roi_min[t]:.2e}, {type_roi_max[t]:.4f}]"
            )

    # 按角色统计
    char_bids: dict[str, list[float]] = {}
    for b in bids:
        char_bids.setdefault(b.character_name, []).append(b.roi)
    parts.append(f"\n### 角色参与度")
    for name in sorted(char_bids.keys()):
        rois = char_bids[name]
        parts.append(f"- **{name}**：{len(rois)} 条，最高 ROI {max(rois):.4f}")

    return "\n".join(parts)